---
layout: post
title:  "Symbols, libraries and One Definition Rule"
date:   2024-11-3 09:22:46 +0800
tags: [c++]
---


In this post, I talk about declaration and definition and their relationship with symbols and code in binaries. Then I discuss library dependency issues and finally the ODR rule. Those are things that we normally don't care about. However, understanding them give us more control over the binaries we produce.

* toc
{:toc}

## Declaration and Definition

Declaration determines symbols in binary; definition determines code in binary. A definition is itself a declaration. A declaration in a translation unit give us a *promise* that the declared entity exist in *somewhere* in the final *executable*. For example, when we declare `void f();` we make a promise that a function called `f` can be used, it might be implemented in current tranlation unit, or it can be implemented in other translation unit. When we declare `class S{..};` we make a promise that a type called `S` can be used and compiled in this translation unit, we can use the member functions and members of it in this translation unit and the implementation of those member functions might be elsewhere. 

A declaration and definition can be about *data* or *code*. They differs in what it really means for declaration and definition.

### Data declaration and definition

For data, such as C++ built-in types and user-defined types, a declaration decides the *memory* layout of the data. A definition decides a concrete *instance* of the data. The key points here are:

- Data declaration only says that *all this type of data must be of this kinds of memory layout*
- Data definition says that *here you have an instance of this kinkds of data, it's address in memory is ...*

`class S{...}` is *declaration*; `S s;` is *definition*. A definitiion *requires* the compiler to allcoate memory for this definition. A declaration *tells* compiler *how* to allocate memory for this specific type.

Saying that *declaration does not occupy memory* is correct but often misleading. It's misleading in that it sounds that declaration have nothing to do with memory, which is wrong. A declaration *determines* how for the compiler to allocate memory. It's better to say like this:

**Declaration tells compiler how to allocate memory; Definition asks for memory from the compiler**

### Code declaration and definition

For code, declaration and definition meanings are a little different. A declaration of code decides *signature* of a function. A definition of code decides *implementation* of a function. `int f(double);` declares code that accept `double` and returns `int`. `int f(double) {...}` defines *what to do* with this function, this definition asks for memory from the compiler to store codes. As we can see, it's more complicated than simple data. We can summarize:

- Code declaration says that *function should be used in this *form* and compiler should allocate memory according to this signature*
- Code implementation says that *here is the code for the execution of this function and here it's address in memory is ...*

Difference between data and code declaration and definition is sutle:

- Data declaration alone does not produce symbols in binary, while code declaration produce symbols in binary
- Multiple data definition(with different names) can be made for one data declaration, while only one definition can be made for code declaration in one translation unit

### Classes are combination of data and code

For declaration and definition of classes, it's only a combination of data and code. The data members of a class are data declarations. The member functions of a class are code declarations. Besides:

- All class's member functions that are implemented inside the class declaration are in-lined

Except for that, class is not that special with stand alone types and functions in delcaration and definition.

## Symbols and libraries

Data definitions(global variables) and code declaration(global functions, class member functions..) will produce symbols in binary. Symbols can be categorized into *defined* and *undefined*:

- Defined(T): thoese are symbols that current translation unit or library *provides*
- Undefined(U): thoese are symbols that current translation unit or library *requires* from outside

Normally, every object file and shared library file contains a section `.symtab` to store all symbols.

### Static libraries

Static libraries are archives of object files. Static libraries are not *linked*, which have many implications:

- Multiple definition of data and function can exist in different object files
- When a static library depends on other static libraries or shared libraries:
  - Only header files of those static libraries and shared libraries are actually required by this static library
  - Binaries of thoese dependees are not required, since static libraries are *not* linked
  - Static libraries does not contain the information of it's dependees

Above obersevations are roots of some interesting behaviors of cmake, if A is static lib we are building, B and C are two libs that A depends on. Let's suppose B is static and C is dynamic.:

- A only needs B and C's header file location to succesfully compile
- After compilation, Inside A's binary there are no B or C's dependency information

If in A's public API, there is no use of B or C's any declaration or definitions(only includes B or C's header in cpp file), the normal way to link to B and C is to use *PRIVATE* keyword, since A's public API does not refer to B or C's headers. When A as a library is depended by executable D, D will have the problem of finding symbols in B and C during linking time, because there is no information in binary A to locate B and C! So cmake is smart enough to have a PRIVATE-becomes-PUBLIC behaviour for static libraries. See: [[CMake] Difference between PRIVATE and PUBLIC with target_link_libraries](https://cmake.org/pipermail/cmake/2016-May/063400.html)

If A is a shared lib, the situation is even more complex:

- For B, all depended code in B will be copied into A already, D does not need B's binary anymore(might still need it's headers!!)
- For C, even though it's not copied into A, but inside A there will be information record in DT_NEEDED section that says that A depend on C, so D can find C according to this information, **both at compile/link time and load time!!**. During load time the dynamic linker will read info from A and load C into program automatically.

About in which scenario PRIVATE keyword can be used:
  - If in A's API there is any header dependency, PUBLIC should be used.
  - If in A's API there is no header depencency:
    - If A is static: if A's binary depend on B or C, PUBLIC should be used.
    - If A is shared:
      - For static lib B, if A has binary dependency on B, PUBLIC should be used, otherwise PRIVATE can be used: **A only used B's declaration headers in A's source file**
      - For shared lib C:
        - If A only used C's declaration headers in A's source file, hence no binary dependency, PRIVATE can be used. Otherwise:
          - If A is linked during compile time, then C's information already inside DT_NEEDED section, PRIVATE keyword can be used, when A is used to link an executable, **linker will find C according to DT_NEEDED information**.
          - If A is not linked during compile time, then C's information is not inside DT_NEEDED section, when A is used to link an executable, linker will need C specifed on command, so PUBLIC keyword should be used.

**Header only contains subset of symbols that a libary uses. Binaries contain all the symbols used.**. From point view of cmake, header and binary dependency are independent from each other: each one can exist independently from each other and co-exist with each other.

The key difference here is that static libraries are not *linked* and shared libraries are all *linked* already. Again, if in A's public API B and C's headers are used, then we need to change the keyword from PRIVATE to PUBLIC, then we will not have above problem anymore.

One last thing about static libraries is that when it's used only the relevent object files will be copied, not the whole archive. The linker copies code **in the unit of object files**. But if instead we seperately give the object files to gcc compiler in command, all the object files, even if they are not used by the final program will be copied into the executable.

### Shared libraries

Shared libraries are *linked*(not necessarily fully linked, might contain unresolved symbols) executable files:

- When a shared lib A depend on another static lib B:
  - A *absorbs* B in binary level and in API(headers) level, after compilation and linking, in the eye of A there is no B anymore
  - Thanks to the PRIVATE-becomes-PUBLIC behaviour mentioned above, all B's dependencies will be passed into A
  - If A is about to be exported as a library, relevent headers of B, more in general relevent headers of all dependent static libs of A, should also be exported together with A's headers, as long as thoese headers are used in A's public API. 
- When a shared lib A depend on another shared lib B:
  - A *works* with B. After compilation and linking, A stores dependency infomation on B and will see B during load time again
  - If A is about to be exported as a library, and if in A's API B's headers are used, then B is PUBLIC depended. All users of A will automatically depend on B. If in A's API B's header are not used, PRIVATE dependency is used, users of A will not aware of B's existence, since users will not link to B. At load time, linker will load B according to A's dependencies infomation.

Shared libs contains unresloved symbols. Those undefined symbols further can be categorized into:

- Unresolved symbols in linked dependencies: those symbols are *resolved* during compile time and the dependent shared libs infomation are recorded in shared lib
- Unresolved symbols with no known provider at compile time: those symbols are *not resolved* at compile time and the resolution of them are deferred until this shared lib is used with an executable.

#### Symbol visibility

Except for .symtab section, shared libraries also have .dynsym section which stores symbols that this lib defines and symbols that need to be resolved during load time. We can control symbol's visibility in .dynsym with gcc compiler. By default, all symbols that defined in shared lib will appear in .dynsym. We can use `__attribute__((visibility("hidden")))` to hide symbols from appearing here. This specifier has different meanings when used on defined and undefined symbols:

- If it's used on defined symbols inside current lib, this symbol will not be seen outside. Not appear in .dynsym
- If it's used on undefined symbols, this symbol will not appear in .dynsym. If it's definition is not found inside current lib, compiler will issue not-defined error

Visiblilty specifier can be used on both data definitions and code definitions.



### Best practices

When building libraries using cmake:

- Never use PRIVATE when specify static lib's dependencies. Since all it's dependencies info will not be recorded inside it and every user of it will use it's dependencies during final linking when building an executable. Even if PRIVATE is used, cmake is smart enough to behaves like PUBLIC and dismiss the requirement.
- Use PRIVATE when specify shared lib's dependencies if this dependency's header file not appear inside shared lib's public API. Shard lib remembers what it depends on.
- When shared lib depend on static lib, properly manage the header files of the static lib. Install relevent static lib's headers into share lib's headers set. Note that we do not need to worry about the dependee static lib's headers locations if current shared lib is used inside current build system, again thanks to the PRIVATE-becomes-PUBLIC behaviour for static libraries. However, if the shared lib will be exported and used by clients, proper header file installation is required.
- Use symbol control: .dynsym will be loaded into memory when program is running. If a symbol is not used by outside libs and exist in .dynsym, it's a waste of memory and a slow down of program loading phase. It will also have the problem of multiple definition, although not intentionally by programmer, which will leads to unexpected behaviors. We will talk about this when we talk about one definition rule later.

## One definition rule

For definition of ODR, see [Definitions and ODR (One Definition Rule)](https://en.cppreference.com/w/cpp/language/definition). I only share what I get from experiment and it's implifications in linking.

### ODR check during linking

Static linking

This is when *executable* files are generated, including *executable* and *shared libraries*. During static linking, multiple *object* files are processed and merged into one *executable* file. ODR rules are checked during this phase, for example if multiple defintions exist in more than one *object* file, errors will be issued. Note that *object* file, aka translation unit is the smallest unit that are being operated by compiler. If static libraries are being linked, *object* files inside this archive file is choosed and used atomically. Use *object* file(one translation unit) as the smallest unit is based on that:
  - If one symbol, for example a function name, is used from this TU, it is possible that this funtion will call other funtion or variables inside this same TU. If linker only abstract the funtion itself, it need to know the detail of the inner structure of this translation unit, which is the job of the compiler, not the linker. So, for simplicity, linker treat TU atomically.

Dynamic linking - Compile time

This is when *executable* depend on another *shared library*. Linker will NOT check ODR and use the first one it can find.
  - If the *executable* is dynamic libraries, and if it depend on another dynamic library, for example *liba.so*, then if not specially handled with linking options, *liba.so* can be linked and NOT linked during this phase, since dynamic libraries symbols are resolved during load time. But the resulting shared libraries binary is a little bit different:
      - If *liba.so* is linked at this phase, in the *metadata*, the DT_NEEDED section of this library will contain *liba.so* and will automatically loaded during load time.
      - If *liba.so* is not linked at this phase, there will be no *liba.so* in DT_NEEDED section. This means *liba.so* will not automatically loaded during load time. This dependency management is deferred for the executable which use this shared library.
      - Other than that, the code inside the shared library is the same and shared lib can both be built succesfully.

Dynamic linking - Run time

This is when *executable* are being loaded. Linker will NOT check ODR and use the first one it can find. However, even though linker does not check ODR, it implement ODR strictly: if there are multiple defintions, the first one will be used for all.

### Which definition to use?

In static libs there might be multiple definitions for the same symbols name in different object files(see [experiment](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR/static)). In shared libs there might be multiple definitions for the same symbols in different shared libs when those libs are both required by an executable(see [experiment](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR/shared)). When an executable is linked to those libs, how the compiler choose definitions if there are multiple definitions available? The answer is rather interesting:

**There is no such problem in the eye of the linker, since the linker just use the definition that it first find and the resolution process is finished**

The linker is *lazy*, it does not tries to find all available options and decides which one to use. Instead, the linker find the available one and says: *oh! here you are!* and stop searching process. The first symbol apperance wins and is used by the linker.

### Data definitions are special

Data definitions are special in that it not only involves data memory allocation, it also involves *construction and initialization* code execution. For example if the linker tries to find one global variable definition and it finds one in shared lib A, all hereafter apperance of this symbol will be treated as the same definition. If in shared lib B there is also this symbol, this symbol will be addressed in lib A's memory mappings, the memory of the same definition in lib B will *not* be used, since lib A's definition appears *first*.

But, a data definition not only is about memory, it's also about construction and initialization. In out example lib A and lib B both will construct and initialize at lib A's symbols address, which means that this data definition symbol will be constructed and initialized **two times**. I encountered one such situation once:

- Static lib A contains global variable `a`
- Lib A is linked into shared lib S1
- Lib A is linked into shared lib S2
- S1 and S2 are both linked into executable E
- In `a`'s construction and initialization code, there is some checking that says it can not be initialized twice, otherwise program terminates.

The above situation will terminate the program and the reason is that `a` will be constructed twice. Problem reproduction can be found at [here](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR).

### Code definitions are influenced by optimization

Since the linker only respect the first appearance of symbols, if a code definition symbol, such as a function is in-lined by the compiler, there will be no such problem. And whether a function is inlined or not can be decided by the optimization level of the compiler. So different opitimization levels might produce different code behaviors. Take an example:

- Lib A has it's own implementation of function `f`
- main.cpp also has an implementation of function `f`
- main.cpp depends and links to lib A

When compiled with different optimization levels:

- If `f` is inlined, lib A will use `f` in lib A
- If `f` is not inlined, lib A will refer `f` in main.cpp's source file and use it's implementation, since the linker find the `f` implementation in main.cpp first

This video demonstrate this problem very well: [C++ Linkers and the One Definition Rule - Roger Orr - ACCU 2024](https://www.youtube.com/watch?v=HakSW8wIH8A)


### How template cope with ODR

Templates, such as standard libraries, are instantiated in each translation unit. Inside one translation unit, the compiler will only instantiate one defintion for one particular template parameter. But what happens during link time? Since all translation unit might instantiate the same template argument, which is basically for certain because every body is using standard library. This can be solved possibly in two ways:

- Make all template instantiation in-line
- At link time, use the first instantiation that appear to the linker

The first approach avoid problems by removing any symbols. The second approach just goes the normal way. But this approach brings another question: if lib A use lib B's implemetentation code, how the linker manage the load and unload sequence of lib A and lib B, so as to avoid any disaster during runtime? I asked this problem in StackOverflow, and I think the answer is satifying: [template instantiation and symbol resolution problem
](https://stackoverflow.com/questions/79147491/template-instantiation-and-symbol-resolution-problem?noredirect=1#comment139562798_79147491). 

> Start with the obvious: libraries are loaded in one order, unloaded in the reverse order, exactly so that non-cyclical dependencies can work.
> Now ask the question again: how can the dynamic linker resolve a symbol so that it's not prematurely unloaded? The answer is trivial: just use the first occurrence. It will be unloaded last.
> Note that most std::vector<std::string> methods are likely to be inlined and simply won't appear in any library, precisely because they're templates. operator[] for instance is not a whole lot more than a simple addition.

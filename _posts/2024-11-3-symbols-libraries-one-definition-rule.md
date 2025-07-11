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

Declaration determines symbols in binary; definition determines code in binary. A definition is itself a declaration. A declaration in a translation unit gives us a *promise* that the declared entity exists *somewhere* in the final *executable*. For example, when we declare `void f();` we make a promise that a function called `f` can be used, it might be implemented in the current translation unit, or it can be implemented in another translation unit. When we declare `class S{..};` we make a promise that a type called `S` can be used and compiled in this translation unit, we can use the member functions and members of it in this translation unit and the implementation of those member functions might be elsewhere. 

A declaration and definition can be about *data* or *code*. They differ in what they really mean for declaration and definition.

### Data declaration and definition

For data, such as C++ built-in types and user-defined types, a declaration decides the *memory layout* of the data. A definition decides a concrete *instance* of the data. The key points here are:

- Data declaration only says that *all data of this type must have this kind of memory layout*
- Data definition says that *here you have an instance of this kind of data, its address in memory is ...*

`class S{...}` is a *declaration*; `S s;` is a *definition*. A definition *requires* the compiler to allocate memory for this definition. A declaration *tells* the compiler *how* to allocate memory for this specific type.

Saying that *declaration does not occupy memory* is correct but often misleading. It's misleading in that it sounds like declarations have nothing to do with memory, which is wrong. A declaration *determines* how the compiler should allocate memory. It's better to say like this:

**Declaration tells compiler how to allocate memory; Definition asks for memory from the compiler**

### Code declaration and definition

For code, declaration and definition meanings are a little different. A declaration of code decides the *signature* of a function. A definition of code decides the *implementation* of a function. `int f(double);` declares code that accepts `double` and returns `int`. `int f(double) {...}` defines *what to do* with this function, this definition asks for memory from the compiler to store code. As we can see, it's more complicated than simple data. We can summarize:

- Code declaration says that *function should be used in this *form* and compiler should allocate memory according to this signature*
- Code definition says that *here is the code for the execution of this function and here its address in memory is ...*

Difference between data and code declaration and definition is subtle:

- Data declaration alone does not produce symbols in binary, while code declaration produces symbols in binary
- Multiple data definitions (with different names) can be made for one data declaration, while only one definition can be made for a code declaration in one translation unit

### Classes are combination of data and code

For declaration and definition of classes, it's only a combination of data and code. The data members of a class are data declarations. The member functions of a class are code declarations. Besides:

- All class's member functions that are implemented inside the class declaration are *potentially* inlined (not guaranteed to be inlined)

Except for that, class is not that special compared to standalone types and functions in declaration and definition.

## Symbols and libraries

Data definitions(global variables) and code declaration(global functions, class member functions..) will produce symbols in binary. Symbols can be categorized into *defined* and *undefined*:

- Defined(T): those are symbols that current translation unit or library *provides*
- Undefined(U): those are symbols that current translation unit or library *requires* from outside

Normally, every object file and shared library file contains a section `.symtab` to store all symbols.

### Symbol tables

1. Symbols are a collection of items that describe where the name is defined and other attributes of symbols.It includes:
   - Symbols that are defined in this object file
   - Symbols that are referenced by this object file
2. Only globals, including global function names and variables, and static local variables have names in symbol table. Local variable do not have names in symbol table
3. `.symtab` and `.dynsym` section of ELF file store symbol table, difference:
   - `.symtab` stores all symbols; `.dynsym` stores symbols that to be used by dynamic linker: either symbols that provided by this object file or symbols that need to find in another shared libs.
   - `.symtab` do not need to load into memory during execution
   - `.dynsym` must be loaded into memory, and used to do dynamic symbol resolution
   - `.dynsym` is a subset of `.symtab`
4. Compiler generate one symbol item whenever it encounter a global or static names during compilation
   - This means if one symbol is not used in program, compiler will not generate the symbol, for example, if only define `extern double data`, plus not using it inside any function, their will be no `data` symbol, because it is `extern` and never used inside this object file, meaning that it has no relationship with this object file. But if define `double data`, then `data` is valid symbol because, this means that this object file has a global name `data`. `extern double data` is *declaration*, while `double data` is *definition*. Only have *declaration*, but not using it, does not add symbol to tables. Defintion only will add symbols to table.
   - **Symbols defined but ​​unused​​ within the object file are still generated. They represent potential exports or data. Symbols merely declared but ​​unused​​ do ​​not​​ get an entry.**. At the source code level, if a declaration is not used, it will not be added into symbol tables, so it will not generate *undefined reference...* error during linking, since linker will only resolve symbols inside symbol table.

### Static libraries

Static libraries are archives of object files. Static libraries are not *linked*, which has many implications:

- Multiple definitions of data and functions can exist in different object files
- When a static library depends on other static libraries or shared libraries:
  - Only header files of those static libraries and shared libraries are actually required by this static library
  - Binaries of those dependees are not required, since static libraries are *not* linked
  - Static libraries do not contain the information of their dependees

When it's used, only the relevant object files will be copied, not the whole archive. The linker copies code **in the unit of object files**. But if instead we separately give the object files to gcc compiler in command, all the object files, even if they are not used by the final program, will be copied into the executable.

### Shared libraries

Shared libraries are *linked* (not necessarily fully linked, might contain unresolved symbols) executable files:

- When a shared lib A depends on another static lib B:
  - A *absorbs* B at binary level, after compilation and linking, in the eyes of A there is no B anymore
  - Thanks to the PRIVATE-becomes-PUBLIC behavior mentioned above, all B's dependencies will be passed into A
  - If A is about to be exported as a library, relevant headers of B, more in general relevant headers of all dependent static libs of A, should also be exported together with A's headers, as long as those headers are used in A's public API.
    - Or lib B will still be used as individual lib and is required in downstream target that depends on A, but this time only the headers of B are actually used. This can lead to another problem, that is when lib B is linked to multiple shared libs: Problem reproduction can be found at [here](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR).
- When a shared lib A depends on another shared lib B (A needs B's header to compile, but can link or not link to B during compile time):
  - A *works* with B. After compilation and linking, A stores dependency information on B and will see B during load time again (if B is linked during compile time, otherwise there is no B's information in A)
  - See more in *More about libraries* section

Shared libs contain unresolved symbols. Those undefined symbols can further be categorized into:
- Unresolved symbols in linked dependencies: those symbols are *resolved* during compile time and the dependent shared libs information are recorded in shared lib
- Unresolved symbols with no known provider at compile time: those symbols are *not resolved* at compile time and the resolution of them is deferred until this shared lib is used with an executable.

### More about libraries

If A is a static lib we are building, B and C are two libs that A depends on. Let's suppose B is static and C is dynamic:

- A only needs B and C's header file location to successfully compile
- After compilation, inside A's binary there are no B or C's dependency information

If in A's public API, there is no use of B or C's any declaration or definitions (only includes B or C's header in cpp file), the normal way to link to B and C is to use *PRIVATE* keyword, since A's public API does not refer to B or C's headers. When A as a library is depended on by executable D, D will have the problem of finding symbols in B and C during linking time, because there is no information in binary A to locate B and C! So cmake is smart enough to have a PRIVATE-becomes-PUBLIC behavior for static libraries. See: [[CMake] Difference between PRIVATE and PUBLIC with target_link_libraries](https://cmake.org/pipermail/cmake/2016-May/063400.html)

If A is a shared lib, the situation is even more complex:

- For B, all depended code in B will be copied into A already, D does not need B's binary anymore (might still need its headers!!)
- For C, even though it's not copied into A, but inside A there will be information recorded in DT_NEEDED section that says that A depends on C, so D can find C according to this information, **both at compile/link time and load time!!**. During load time the dynamic linker will read info from A and load C into program automatically.

About in which scenario PRIVATE keyword can be used:
  - If in A's API there is any header dependency, PUBLIC should be used.
  - If in A's API there is no header dependency:
    - If A is static: if A's binary depends on B or C, PUBLIC should be used.
    - If A is shared:
      - For static lib B, if A has binary dependency on B, PUBLIC should be used, otherwise PRIVATE can be used: **A only used B's declaration headers in A's source file**
      - For shared lib C:
        - If A only used C's declaration headers in A's source file, hence no binary dependency, PRIVATE can be used. Otherwise:
          - If A is linked during compile time, then C's information is already inside DT_NEEDED section, PRIVATE keyword can be used, when A is used to link an executable, **linker will find C according to DT_NEEDED information**.
          - If A is not linked during compile time, then C's information is not inside DT_NEEDED section, when A is used to link an executable, linker will need C specified on command, so PUBLIC keyword should be used.
         
Refer to experiment: [shared_lib_link](https://github.com/shan-weiqiang/lab/tree/main/shared_lib_link)

From point of view of cmake, header and binary dependency are independent from each other: each one can exist independently from each other and co-exist with each other:

1. When building and linking static libraries or shared libraries, only header files are required; all symbols can be unresolved.

2. When building and linking executables, all dependent libraries must be present to the compiler and linker! Including those recursively dependent libraries.

3. Compiler and linker will search libraries according to:
   - Command line arguments (decided by CMake)
   - DT_NEEDED section (in shared libraries)

#### Symbol visibility

Except for .symtab section, shared libraries also have .dynsym section which stores symbols that this lib defines and symbols that need to be resolved during load time. We can control symbol's visibility in .dynsym with gcc compiler. By default, all symbols that are defined in shared lib will appear in .dynsym. We can use `__attribute__((visibility("hidden")))` to hide symbols from appearing here. This specifier has different meanings when used on defined and undefined symbols:

- If it's used on defined symbols inside current lib, this symbol will not be seen outside. Not appear in .dynsym
- If it's used on undefined symbols, this symbol will not appear in .dynsym. If its definition is not found inside current lib, compiler will issue not-defined error

Visibility specifier can be used on both data definitions and code definitions.

### Best practices

When building libraries using cmake:

- Never use PRIVATE when specifying static lib's dependencies. Since all its dependencies info will not be recorded inside it and every user of it will use its dependencies during final linking when building an executable. Even if PRIVATE is used, cmake is smart enough to behave like PUBLIC and dismiss the requirement.
- Use PRIVATE when specifying shared lib's dependencies if this dependency's header file does not appear inside shared lib's public API. Shared lib remembers what it depends on.
- When shared lib depends on static lib, properly manage the header files of the static lib. Install relevant static lib's headers into shared lib's headers set. Note that we do not need to worry about the dependee static lib's headers locations if current shared lib is used inside current build system, again thanks to the PRIVATE-becomes-PUBLIC behavior for static libraries. However, if the shared lib will be exported and used by clients, proper header file installation is required.
- Use symbol control: .dynsym will be loaded into memory when program is running. If a symbol is not used by outside libs and exists in .dynsym, it's a waste of memory and a slow down of program loading phase. It will also have the problem of multiple definition, although not intentionally by programmer, which will lead to unexpected behaviors. We will talk about this when we talk about one definition rule later.

## One definition rule

For definition of ODR, see [Definitions and ODR (One Definition Rule)](https://en.cppreference.com/w/cpp/language/definition). I only share what I get from experiment and its implications in linking.

### ODR check during linking

Static linking

This is when *executable* files are generated, including *executables* and *shared libraries*. During static linking, multiple *object* files are processed and merged into one *executable* file. ODR rules are checked during this phase, for example if multiple definitions exist in more than one *object* file, errors will be issued. Note that *object* file, aka translation unit, is the smallest unit that is being operated by the compiler. If static libraries are being linked, *object* files inside this archive file are chosen and used atomically. Using *object* file (one translation unit) as the smallest unit is based on that:
  - If one symbol, for example a function name, is used from this TU, it is possible that this function will call other functions or variables inside this same TU. If linker only extracts the function itself, it needs to know the detail of the inner structure of this translation unit, which is the job of the compiler, not the linker. So, for simplicity, linker treats TU atomically.

Dynamic linking - Compile time

This is when *executable* depends on another *shared library*. Linker will NOT check ODR and use the first one it can find.
  - If the *executable* is a dynamic library, and if it depends on another dynamic library, for example *liba.so*, then if not specially handled with linking options, *liba.so* can be linked and NOT linked during this phase, since dynamic libraries symbols are resolved during load time. But the resulting shared libraries binary is a little bit different:
      - If *liba.so* is linked at this phase, in the *metadata*, the DT_NEEDED section of this library will contain *liba.so* and will be automatically loaded during load time.
      - If *liba.so* is not linked at this phase, there will be no *liba.so* in DT_NEEDED section. This means *liba.so* will not be automatically loaded during load time. This dependency management is deferred for the executable which uses this shared library.
      - Other than that, the code inside the shared library is the same and shared lib can both be built successfully.

Dynamic linking - Run time

This is when *executables* are being loaded. Linker will NOT check ODR and use the first one it can find. However, even though linker does not check ODR, it implements ODR strictly: if there are multiple definitions, the first one will be used for all.

### Which definition to use?

In static libs there might be multiple definitions for the same symbol name in different object files (see [experiment](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR/static)). In shared libs there might be multiple definitions for the same symbols in different shared libs when those libs are both required by an executable (see [experiment](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR/shared)). When an executable is linked to those libs, how does the compiler choose definitions if there are multiple definitions available? The answer is rather interesting:

**There is no such problem in the eyes of the linker, since the linker just uses the definition that it first finds and the resolution process is finished**

The linker is *lazy*, it does not try to find all available options and decide which one to use. Instead, the linker finds the available one and says: *oh! here you are!* and stops the searching process. The first symbol appearance wins and is used by the linker.

### Data definitions are special

Data definitions are special in that they not only involve data memory allocation, they also involve *construction and initialization* code execution. For example, if the linker tries to find one global variable definition and it finds one in shared lib A, all hereafter appearances of this symbol will be treated as the same definition. If in shared lib B there is also this symbol, this symbol will be addressed in lib A's memory mappings, the memory of the same definition in lib B will *not* be used, since lib A's definition appears *first*.

But, a data definition is not only about memory, it's also about construction and initialization. In our example, lib A and lib B both will construct and initialize at lib A's symbol address, which means that this data definition symbol will be constructed and initialized **two times**. I encountered one such situation once:

- Static lib A contains global variable `a`
- Lib A is linked into shared lib S1
- Lib A is linked into shared lib S2
- S1 and S2 are both linked into executable E
- In `a`'s construction and initialization code, there is some checking that says it cannot be initialized twice, otherwise program terminates.

The above situation will terminate the program and the reason is that `a` will be constructed twice. Problem reproduction can be found at [here](https://github.com/shan-weiqiang/cplusplus/tree/main/ODR).

### Code definitions are influenced by optimization

Since the linker only respects the first appearance of symbols, if a code definition symbol, such as a function, is inlined by the compiler, there will be no such problem. And whether a function is inlined or not can be decided by the optimization level of the compiler. So different optimization levels might produce different code behaviors. Take an example:

- Lib A has its own implementation of function `f`
- main.cpp also has an implementation of function `f`
- main.cpp depends and links to lib A

When compiled with different optimization levels:

- If `f` is inlined, lib A will use `f` in lib A
- If `f` is not inlined, lib A will refer to `f` in main.cpp's source file and use its implementation, since the linker finds the `f` implementation in main.cpp first

This video demonstrates this problem very well: [C++ Linkers and the One Definition Rule - Roger Orr - ACCU 2024](https://www.youtube.com/watch?v=HakSW8wIH8A)

### How templates cope with ODR

Templates, such as standard libraries, are instantiated in each translation unit. Inside one translation unit, the compiler will only instantiate one definition for one particular template parameter. But what happens during link time? Since all translation units might instantiate the same template argument, which is basically certain because everybody is using standard library. This can be solved possibly in two ways:

- Make all template instantiation in-line
- At link time, use the first instantiation that appears to the linker

The first approach avoids problems by removing any symbols. The second approach just goes the normal way. But this approach brings another question: if lib A uses lib B's implementation code, how does the linker manage the load and unload sequence of lib A and lib B, so as to avoid any disaster during runtime? I asked this problem in StackOverflow, and I think the answer is satisfying: [template instantiation and symbol resolution problem
](https://stackoverflow.com/questions/79147491/template-instantiation-and-symbol-resolution-problem?noredirect=1#comment139562798_79147491). 

> Start with the obvious: libraries are loaded in one order, unloaded in the reverse order, exactly so that non-cyclical dependencies can work.
> Now ask the question again: how can the dynamic linker resolve a symbol so that it's not prematurely unloaded? The answer is trivial: just use the first occurrence. It will be unloaded last.
> Note that most std::vector<std::string> methods are likely to be inlined and simply won't appear in any library, precisely because they're templates. operator[] for instance is not a whole lot more than a simple addition.

---
layout: post
title:  "C++ template name lookup rules"
date:   2023-05-01 19:22:46 +0800
tags: [c++]
---


When defining template class or function template, knowing how these template parameters are instantiated during compiling time is important to correctly use them. This article tries to explain(but with no full coverage) the order behind the name look up. The template parameter name look up is complex. This article only cover the commonly used cases. For a full understanding of the issue, please refer to official documentation or C++ ISO standard.


* toc
{:toc}

# Types of template parameters

Each parameter in *parameter-list* may be:

- a non-type template parameter;
- a type template parameter;
- a template template parameter.

## non-type template parameters

- template parameter can be non-type
  
    ```cpp
    template<const int* pci>
    struct X {};
     
    int ai[10];
    X<ai> xi; // OK: array to pointer conversion and cv-qualification conversion
    ```
    

## type template parameter

### template parameters without name

- template parameter name is optional!!

## template template parameter

```cpp
template<typename T>
class my_array {};
 
// two type template parameters and one template template parameter:
template<typename K, typename V, template<typename> typename C = my_array>
class Map
{
    C<K> key;
    C<V> value;
};
```

# The base rule: "Two Phase Name Lookup”

When the compiler parses the template relevant code, it resolves the names in the template in two stages:

- First at the template definition
- Second at the instantiation of the template

Here is an example of this basic rule:

`EXAMPLE_#1` :

```cpp
#include <iostream>

template <typename T> struct SomeStruct {
  void f() { std::cout << "Hello\n" << sizeof(T) << '\n'; }
};

template <typename T> struct DerivedStruct : public SomeStruct<T> {
  void h() {

    //  Nok, because f() is non-template dependent, so name lookup happens
    //  at phase one, but during this time there is no f() defined,
    //  because SomeStruct has not been instantiated yet
    // f();

    //  Ok, because 'this' is template dependent, f() lookup happens at
    //  phase two, at this time SomeStruct has been instantiated and f() is
    //  available
    this->f();
  }
};

int main(int argc, char const *argv[]) {
  DerivedStruct<int>().h();
  return 0;
}
```

As in above example, there are differences when name look up and definition binding for `f()` and `this->f()`.  That is because they belong to two different name types:

- Dependent names: or template dependent names. These are names that can be different for different template parameter types(type template parameter) or parameter values(non-type template parameter). In this example, `this->f()` is template dependent, because, `this` can be `DerivedStruct<int>` or it can be `DerivedStruct<double>`
- Non-dependent names: or non template dependent names. These are names that is always the same between different instantiations. In this example `f()` is non template dependent name, because whether is `DerivedStruct<int>` or `DerivedStruct<double>` , the call for `f()` is the same. It has nothing to do with parameter `T`

# Rules for non template dependent names

Non template dependent names are determined at stage one, namely, template definition.

Here is an example to demonstrate this behaviour:

`EXAMPLE_#2`:

```cpp
#include <iostream>

struct FooStruct;
template <typename T> struct SomeStruct {
  // Since f is non template dependent, it will be looked up and bound here
  // But at this time FooStruct has not been defined(only declaration), the
  // compiler does not know how much memory f will take, so it gives incomplete
  // type error
  FooStruct f;
};

struct FooStruct {};

int main(int argc, char const *argv[]) {
  // Even though at the time of instantiation, the FooStruct is fully defined
  // SomeStruct does not compile because name look up and bound of member f
  // happens at template definition time
  SomeStruct<int>();
  return 0;
}
```

Another example of non template dependent name look up behaviour:

`EXAMPLE_#3` :

```cpp
#include <iostream>

void f(double data) { std::cout << "Double type recieved\n"; }

template <typename T> struct SomeStruct {
  // Here f is already looked up and bound with f(double data)
  void some_method() { f(3); }
};

// Even there is a more matched version of f(int data), it will not be called
void f(int data) { std::cout << "Int type recieved\n"; }

int main(int argc, char const *argv[]) {

  // This will call f(int data), because it is more compatible
  f(3);
  // This will call f(double data), because even there is more compatible
  // version, the f is looked up and bound before f(int data) is available
  SomeStruct<int>().some_method();
  return 0;
}
```

- In above example, the `f(int data)` is not visible to `SomeStruct`

# Rules for template dependent names

## The normal case

The behaviour is clear when compared with following example with `EXAMPLE_#2`

`EXAMPLE_#4` , which makes the `f` template dependent in `EXAMPLE_#2`. Now the code compiles:

```cpp
#include <iostream>

template <typename T> struct FooStruct;
template <typename T> struct SomeStruct {
  // Since f is template dependent, it will be looked up and bound not at here
  // but at the instantiation; Even though here FooStruct is not defined yet
  // it does not effect the compile
  FooStruct<T> f;
};

template <typename T> struct FooStruct {};

int main(int argc, char const *argv[]) {
  // Here the FooStruct is fully defined, code compiles
  SomeStruct<int>();
  return 0;
}
```

## Different behaviour when using non-ADL and ADL

Firstly a basic understanding of `non-ADL` and `ADL` should be required, please refer to [Argument-dependent lookup - cppreference.com](https://en.cppreference.com/w/cpp/language/adl) for detailed info. For an extremely simplified explanation of what `ADL` does is that:

- When look up a function name, not only in current namespace, but also the namespace of the arguments are added to the look up scope
- For fundamental types, no additional argument namespace is added

Here is an example to demonstrate this behaviour:

`EXAMPLE_#5`

```cpp
#include <iostream>

void f(double data) { std::cout << "Double passed in\n"; }

template <typename T> struct FooStruct;

template <typename T> struct SomeStruct {
  // Since f is template dependent, it will be looked up and bound not at here
  // but at the instantiation; Even though here FooStruct is not defined yet
  // it does not effect the compile
  FooStruct<T> f;
};

template <typename T> struct FooStruct {
  FooStruct() {
    T t;
    // Here f(..) name look up depends on type of T:
    // 1. If non-ADL look up, for example T is of fundamental types(int,
    // double..) the look up scope ends here, it's look up is based on template
    // definition context; Functions declared after this template definition are
    // not visible.
    // 2. If ADL look up, for example T is of user defined types, the look up
    // scope will include the namespace where T resides. The look up scope is
    // based on template definition context or template instantiate context,
    // which means that functions declared before the instantiation is also
    // visible.
    f(t);
  }
};
void f(int data) { std::cout << "Int passed in\n"; }

struct UserType {};

void f(UserType data) { std::cout << "UserType passed in\n"; }

int main(int argc, char const *argv[]) {
  // Here whether it's int or double, void f(int data) is not visible to  f(t)
  // in FooStruct constructor. It's a non-ADL look up.
  SomeStruct<int>();
  SomeStruct<double>();
  // Here since UserType is user defined, it's ADL look up. The look up scope is
  // template definition scope or instantiation scope, which means void
  // f(UserType data) is visible.
  SomeStruct<UserType>();
  return 0;
}
```

Output:

```cpp
Double passed in
Double passed in
UserType passed in
```

This behaviour can be summarized in one sentence:

> For template dependent names, adding a new function declaration after template definition does not make it visible, except via ADL(from cppreference.com)
> 

### Why template definition context when non-ADL?

The reason is to not violate the `ODR`(One Definition Rule).

To demonstrate this, let’s make the template a header library.  File `SomeStruct.h` :

```cpp
// SomeStruct.h
#include <iostream>

inline void f(double data){};

template <typename T> struct FooStruct;

template <typename T> struct SomeStruct {
  FooStruct<T> f;
};

template <typename T> struct FooStruct {
  FooStruct() {
    T t;
    f(t);
  }
};
```

Now we have two translation unit that both use the `SomeStruct.h` library, respectively `TU_a.cpp` and `TU_b.cpp` . And they have namespace `A` and namespace `B` respectively.

File `TU_a.cpp`:

```cpp
#include "SomeStruct.h"
#include <iostream>
namespace A {
void f(double data) { std::cout << "Double passed in, at namespace A\n"; }
SomeStruct<double> a();
} // namespace A
```

File `TU_b.cpp` :

```cpp
#include "SomeStruct.h"
#include <iostream>
namespace B {
void f(double data) { std::cout << "Double passed in, at namespace B\n"; }
SomeStruct<double> b();
} // namespace B
```

Let’s analysis what will happen if we compile and link the two translation unit:

- Since `T` is `double` , it’s a non-ADL name look up. Let’s see what will happen if we use template instantiation context for name look up:
    - `TU_a.cpp` will use `A::f`
    - `TU_b.cpp` will use `B::f`
        - Both `TU_a.cpp` and `TU_b.cpp` instantiate the same data type `SomeStruct<double>`, but they have multi definition of `f` , which clearly violates the `ODR`
- So instead of using template instantiation context when non-ADL name look up, compiler use template definition context for name look up, which leads to:
    - `inline void f(double data){};` is use for both `TU_a.cpp` and `TU_b.cpp`
    

### Why template instantiation context when ADL?

The key point is:

- When using ADL look up, the type is user defined, such as `SomeStruct<UserType_A>` or `SomeStruct<UserType_B>` , the types which are instantiated can not be the same
- But with fundamental types, above assertion is not true. Some different translation unit can instantiate the same type, such as `SomeStruct<double>` in the example. To keep the `ODR` rule, it has to use the template definition context for name look up, not template instantiation context.

# Current instantiation

Names that belong to *current instantiation* means that their look up and binding can be done based on current instantiation of the template, no further instantiation is required to compete look up and binding. Following is an example to demonstrate this:

```cpp
#include <iostream>

template <typename T> struct FooStruct {
  // FooStruct<T> is current instantiation because when instantiate this
  // template FooStruct<T> is itself, no additional instantiation is required to
  // determine FooStruct<T>
  FooStruct<T> *ptr;
  //   FooStruct<T*> is NOT current instantiation because when instantiate this
  //   template FooStruct<T>, another instantiation which is FooStruct<T*> is
  //   required.Note: here is an compiling error
  FooStruct<T *> ptr_ptr;

  // Current instantiation, no further instantiations are required
  T c;
  T *c_ptr;
};
```

## `typename` for template dependent types

A name that is not a member of current instantiation and is dependent on template argument is not considered a type, except using `typename` keyword:

Here is an example to demonstrate this:

```cpp
#include <iostream>

template <typename T> struct BarStruct {
  typedef T *ptr_type;
  template <typename U> struct NestedStruct {
    NestedStruct() { std::cout << "Hello\n"; }
  };
};

template <typename T> struct FooStruct {

  // Here ptr_type is not a current instantiation and a member of FooStruct,
  // typename has to be used to indicate that it's a type
  typename BarStruct<T>::ptr_type ni;
};

int main(int argc, char const *argv[]) { FooStruct<double> b; }
```

## `template` for template dependent templates

A name is not considered a template if the name is not a member of current instantiation and depend on template argument, except using `template` keyword:

```cpp
#include <iostream>

template <typename T> struct BarStruct {
  typedef T *ptr_type;
  template <typename U> struct NestedStruct {
    NestedStruct() { std::cout << "Hello\n"; }
  };
};

template <typename T> struct FooStruct {

  // Here NestedStruct<T> is at the same time template and type name; typename
  // and template keywords must be used
  typename BarStruct<T>::template NestedStruct<T> com;
};

int main(int argc, char const *argv[]) { FooStruct<double> b; }
```

Output:

```cpp
Hello
```
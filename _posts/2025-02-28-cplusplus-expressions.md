---
layout: post
title:  "Expressions: type and value category"
date:   2025-02-28 09:22:46 +0800
tags: [c++]
---

According to experience of myself, the most difficult part to understanding C++ is however the most basic one: the `expression`. Only by having a fully understanding of `expression`, one can further have a clear sight about lvalue, rvalue, type deduction, `auto` keyword, universal reference, `decltype`, move semantics,etc. As you can imagine, above mentioned concept are all at the core of C++ 11 and afterwards.

This blog summarize information, concepts, references around `expression`. It does not provide additional knowledge, but act as a understanding note. 

* toc
{:toc}

# Expressions

[C++ expressions](https://en.cppreference.com/w/cpp/language/expressions)

Each C++ expression (an operator with its operands, a literal, a variable name, etc.) is characterized by two independent properties: a type and a value category. Each expression has some non-reference type, and each expression belongs to exactly one of the three primary value categories: *prvalue*, *xvalue*, and *lvalue*.

## Type

An expression can have basic type, user-defined type, const/non-const, reference/non-reference types. However, **If an expression initially has the type “reference to T” (8.3.2, 8.5.3), the type is adjusted to T prior to any further analysis.**, which indicates that expression can have reference types. [Expressions can have Reference Type]>(https://scottmeyers.blogspot.com/2015/02/expressions-can-have-reference-type.html):


>Today I got email about some information in *Effective Modern C++*. The email included the statement, "An expression never has reference type." This is easily shown to be >incorrect, but people assert it to me often enough that I'm writing this blog entry so that I can refer people to it in the future.
>
>Section 5/5 of the Standard is quite clear (I've put the relevant text in bold):
>
>**If an expression initially has the type “reference to T”** (8.3.2, 8.5.3), the type is adjusted to T prior to any further analysis. The expression designates the object >or function denoted by the reference, and  the expression is an lvalue or an xvalue, depending on the expression.
>
>There'd clearly be no need for this part of the Standard if expressions couldn't have reference type.
>
>If that's not enough to settle the matter, consider the type of an expression that consists of a function call. For example:
        >int& f();                // f returns int&
        >auto x = f();            // a call to f
>        
>What is the type of the expression "f()", i.e., the type of the expression consisting of a call to f? It's hard to imagine anybody arguing that it's not int&, i.e., a >reference type. But what does the Standard say? Per 5.2.2/3 (where I've again put the relevant text in bold and where I'm grateful to Marcel Wid for correcting the error >I had in an earlier version of this post that referred to 5.2.2/10):
>
>If the postfix-expression designates a destructor (12.4), the type of the function call expression is void; otherwise, the type of the function call expression is the >return type of the statically chosen function (i.e., ignoring the virtual keyword), even if the type of the function actually called is different. This return type shall >be an object type, a reference type or cv void.
>
>It's very clear that expressions can have reference type. Section 5/5 takes those expressions and strips the reference-ness off of them before doing anything else, but >that's not the same as the reference-ness never being present in the first place.


## Value Category

[C++ value_category](https://en.cppreference.com/w/cpp/language/value_category)


> With the introduction of move semantics in C++11, value categories were redefined to characterize two independent properties of expressions[[5\]](https://en.cppreference.com/w/cpp/language/value_category#cite_note-5):
>
> - *has identity*: it's possible to determine whether the expression refers to the same entity as another expression, such as by comparing addresses of the objects or the functions they identify (obtained directly or indirectly);
> - *can be moved from*: [move constructor](https://en.cppreference.com/w/cpp/language/move_constructor), [move assignment operator](https://en.cppreference.com/w/cpp/language/move_assignment), or another function overload that implements move semantics can bind to the expression.
>
> In C++11, expressions that:
>
> - have identity and cannot be moved from are called *lvalue* expressions;
> - have identity and can be moved from are called *xvalue* expressions;
> - do not have identity and can be moved from are called *prvalue* ("pure rvalue") expressions;
> - do not have identity and cannot be moved from are not used[[6\]](https://en.cppreference.com/w/cpp/language/value_category#cite_note-6).
>
> The expressions that have identity are called "glvalue expressions" (glvalue stands for "generalized lvalue"). Both lvalues and xvalues are glvalue expressions.
>
> The expressions that can be moved from are called "rvalue expressions". Both prvalues and xvalues are rvalue expressions.


```
   ______ ______

  /      X      \

 /      / \      \

|   l  | x |  pr  |

 \      \ /      /

  \______X______/

​      gl    r
```

Above diagram describes the general relationship between *lvalue*(l), *xvalue*(x), *prvalue*(pr), *glvalue*(gl), *rvalue*(r)

## Type vs ValueCategory

Lvalueness or rvalueness of an expression is independent of its type, it’s possible to have lvalues whose type is rvalue reference, and it’s also possible to have rvalues of the type rvalue reference. See examples from [Universal References in C++11, Scott Meyers](https://github.com/shan-weiqiang/cplusplus/blob/main/expression/universal-references-and-reference-collapsing-scott-meyers.pdf):

```c++
Widget makeWidget();
 // factory function for Widget
Widget&& var1 = makeWidget()
 // var1 is an lvalue, but
 // its type is rvalue reference (to Widget)
Widget var2 = static_cast<Widget&&>(var1);
 // the cast expression yields an rvalue, but
 // its type is rvalue reference (to Widget)
```

Note that the valueness of expression `static_cast` is decided by [`static_cast`](https://en.cppreference.com/w/cpp/language/static_cast) itself:

<blockquote>
As with all cast expressions, the result is:

- An lvalue if target-type is an lvalue reference type or an rvalue reference to function type(since C++11);
- A xvalue if target-type is an rvalue reference to object type; [swq: how `std::move` is implemented] (since C++11)
- A prvalue otherwise.
</blockquote>


# Type Deduction

## Deduction context

We consider two occasions where type deduction happens:

- [Function template parameter type deduction]((https://en.cppreference.com/w/cpp/language/template_argument_deduction).)
- `auto`

Additionally, a special kind of type deduction, universal reference is considered. 

During compile time compiler has mainly two ways to deduce template parameter types: from user and auto deduction. In the case of user input, hatever user specifies, compiler will use them. If user specified reference, reference collapsing rules apply. Also in C++ 17, class template parameter type can also be deduced: [Class template argument deduction (CTAD) (since C++17)](https://en.cppreference.com/w/cpp/language/class_template_argument_deduction).

## Function template parameter type deduction

Note: Most content of this paragraph comes from the book: *Effective Modern C++, Scott Meyers*. I only copies them here to make this artical complete.

Take:

```c++
template<typename T>
void f(ParamType param);
f(expr); // deduce T and ParamType from expr

// Above pseudo code can represent most cases, since reference, const are not allowed insdie parameter list: template<typename const T> and template<typename T&> and template<typename T&&> are both not valid. However, when user specify T, const and reference types can be used and reference collapsing rules apply.
```

- Case 1: ParamType is a Reference or Pointer, but not a Universal Reference
  - If expr’s type is a reference, ignore the reference part
  - Then pattern-match expr’s type against ParamType to determine T.
- Case 2: ParamType is a Universal Reference
  - If expr is an lvalue, both T and ParamType are deduced to be lvalue references. That’s doubly unusual. First, it’s the only situation in  template type deduction where T is deduced to be a reference. Second, although ParamType is declared using the syntax for an rvalue reference, its deduced type is an lvalue reference.
  - If expr is an rvalue, the “normal” (i.e., Case 1) rules apply.
- Case 3: ParamType is Neither a Pointer nor a Reference
  - As before, if expr’s type is a reference, ignore the reference part
  - If, after ignoring expr’s reference-ness, expr is const, ignore that, too. If it’s volatile, also ignore that.

## `auto` deduction

It's essentially the same as function template parameter type deduction like above, the mappings relationships are:

- `auto` --> `T`
- Expression before `=` --> `ParamType`
- Expression after `=` --> `expr`

For example: 

```c++
auto x = 27; // case 3 (x is neither ptr nor reference)
const auto cx = x; // case 3 (cx isn't either)
const auto& rx = x; // case 1 (rx is a non-universal ref.)
// T --> auto; const auto& --> ParamType; x --> expr
```

## More about Universal Reference

[Universal References in C++11, Scott Meyers](https://github.com/shan-weiqiang/cplusplus/blob/main/expression/universal-references-and-reference-collapsing-scott-meyers.pdf)

### Reference Collapsing Rules

[C++ Reference](https://en.cppreference.com/w/cpp/language/reference)

- An rvalue reference to an rvalue reference becomes (‘collapses into’) an rvalue reference.
- All other references to references (i.e., all combinations involving an lvalue reference) collapse into an lvalue reference.

### Key Points & Golden Rules

- Remember that “&&” indicates a universal reference only where type deduction takes place.  Where there’s no type deduction, there’s no universal reference.  In such cases, “&&” in type declarations always means rvalue reference.
- Apply std::move to rvalue references and std::forward to universal references
- Only use std::forward with universal references
- **Universal reference type deduction is the only situation a template parameter is deduced as reference(when passed type is of lvalue).**


# Named Variables

Named variables and parameters of rvalue reference type are lvalues. Also from [Universal References in C++11, Scott Meyers](https://github.com/shan-weiqiang/cplusplus/blob/main/expression/universal-references-and-reference-collapsing-scott-meyers.pdf):


```c++
template<typename T>
class Widget {
 ...
 Widget(Widget&& rhs);
 // rhs's type is rvalue reference, but rhs
 // itself is an lvalue
 ...
};
template<typename T1>
class Gadget {
 ...
 template <typename T2>
 Gadget(T2&& rhs);
 // rhs is a universal reference whose type will
 // eventually become an rvalue reference or an
 // lvalue reference, but rhs itself is an lvalue
 ...
};
```


# `decltype`

[C++ decltype](https://en.cppreference.com/w/cpp/language/decltype)

Inspects the declared type of an entity or the type and value category of an expression.
This implies two funtionality of decltype:

1. When used as decltype ( entity ), where entity is unparenthesized id-expression or class memeber expression, it yields
the type of entity
2. When used as decltype ( expression ), where expression is any other expression, it inspects the expression's
value type(eg,T) and value category and yields following types accordingly:

- if value category of expression is xvalue, it yields T&&
- if value category of expression is lvalue, it yields T&
- if value category of expression is prvalue, it yields T

Note: if variable id-expression or class memeber access expression is parenthesized, it is treated as ordinary lvalue
expression(which is reasonable, because named variables are always lvalue expressions)

```c++
class Widget {};
Widget makeWidget() { return Widget(); }

int main() {

  Widget &&var1 = makeWidget();
  // var1 is an lvalue, but
  // its type is rvalue reference (to Widget)
  Widget var2 = static_cast<Widget &&>(var1);
  // the cast expression yields an rvalue, but
  // its type is rvalue reference (to Widget)
  decltype(static_cast<Widget &&>(var1)) var3 = makeWidget();
  //   expression type is Widget &&, value category of expression is xvalue,
  //   first get the non-reference type Widget, so var3 is of Widget&& type.
  Widget &var4 = var2;
  decltype(std::move(var4)) var5 = makeWidget();
  // expression type is Widget &, value category of expression is xvalue; first
  // get the non-reference type Widget, so var5 is of Widget && type

  decltype((var4)) var6 = var2;
  // expression type is Widget &, value category of expression is lvalue; first
  // get the non-reference type Widget, so var6 is of Widget & type

  decltype(makeWidget()) var7 = makeWidget();
  // expression type is Widget , value category of expression is prvalue; first
  // get the non-reference type Widget, so var6 is of Widget  type
}
```

Note: When doing all deduction the expression type `T` will use the non-reference version, since as the standard says:

> If an expression initially has the type “reference to T” (8.3.2, 8.5.3), the type is adjusted to T prior to any further analysis.

## Print valueness

First approach, we can check whether the yield type of decltype(expression) is lvalue or rvalue reference, if rvalue
reference, the expression is xvalue; if lvalue reference, the expression is lvalue; otherwise, the expression is prvalue

```c++
#include <iostream>
#include <utility> // for std::move

class Widget {};
Widget makeWidget() { return Widget(); }

template <typename T> struct value_category {
  static constexpr const char *str() { return "prvalue"; }
};

template <typename T> struct value_category<T &> {
  static constexpr const char *str() { return "lvalue"; }
};

template <typename T> struct value_category<T &&> {
  static constexpr const char *str() { return "xvalue"; }
};

// Macro to check the value category of an expression
#define PRINT_VALUE_CATEGORY(expr)                                             \
  std::cout << "The expression '" #expr "' is a "                              \
            << value_category<decltype((expr))>::str() << std::endl;

int main() {
  Widget &&var1 = makeWidget();
  Widget var2 = static_cast<Widget &&>(var1);
  Widget &var4 = var2;

  PRINT_VALUE_CATEGORY(var1);                         // lvalue
  PRINT_VALUE_CATEGORY(static_cast<Widget &&>(var1)); // xvalue
  PRINT_VALUE_CATEGORY(var4);                         // lvalue
  PRINT_VALUE_CATEGORY((var4));                       // lvalue
  PRINT_VALUE_CATEGORY(std::move(var4));              // xvalue
  PRINT_VALUE_CATEGORY(makeWidget());                 // prvalue
}
```

# `declval`

[C++ declval](https://en.cppreference.com/w/cpp/utility/declval)

`declval` can return a reference to a type, **without going through actual construction**.

Implementation:

```c++
template<typename T>
typename std::add_rvalue_reference<T>::type declval() noexcept
{
    static_assert(false, "declval not allowed in an evaluated context");
}
```

- What `declval` does is simply add rvalue reference to type `T`
- The `static_cast` statement make sure that it can only be used in `unevaluated` context, like inside `decltype`

[Why add rvalue reference, instead of lvalue reference?](https://stackoverflow.com/questions/20303250/is-there-a-reason-declval-returns-add-rvalue-reference-instead-of-add-lvalue-ref/20303350#20303350)

The reason is related to reference collapsing rules: only by adding rvalue reference, `declval` might have the possibility return a rvalue reference, so as to have more possibility to call methods, such as methods that can only be called by rvalue.



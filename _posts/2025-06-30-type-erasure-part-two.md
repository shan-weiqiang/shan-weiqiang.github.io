---
layout: post
title:  "Type Erasure II — std::function"
date:   2025-06-29 10:00:00 +0800
tags: [cpp, type-erasure, polymorphism]
---

> **Editor's note:** This article has been revised to distinguish compile-time
> adapter generation, construction-time binding, and runtime dispatch. The
> expanded taxonomy appears in
> [Polymorphism, Type Erasure, and std::function](https://shan-weiqiang.github.io/2026/08/23/polymorphism-type-erasure-std-function.html).

`std::function<R(Args...)>` is a hybrid abstraction. Templates generate
callable-specific adapters while the callable type is known; construction
stores a callable together with its matching adapters; invocation later uses a
uniform erased signature.

* toc
{:toc}

## Original implementation analysis

std::function Implementation:

---

**Inherits `_Function_base`** to get the storage, responsible for data, itself contains `_M_invoker`:
- **`_M_functor`**: A union structure that stores actual callable, might be pointer or heap allocated callable objects. The `_M_init_functor` will move `__f`, the callable to be stored in `_M_functor`
- **`_M_manager`**: A function pointer in `_Function_handler` to create/destroy/... the `_M_functor`
- **`_M_invoker`**: A function pointer in `_Function_handler` to call the callable
- **`&_My_handler::_M_invoke`/`&_My_handler::_M_manager`**: Static functions bound with `_Functor` type providing clone/destroy operations, which operates on the stored callable object. So the stored callable must be compatible with those static function pointers, which is done during construction.

---

**Points to `_Function_handler` type** that do the type erasure of the passed actual callable type, responsible for code

---

After construction, the binding is fixed to a specific `_functor`, aka user callable. Even though `std::function`'s type is only determined by callable signature, `_Function_handler`'s type is also determined by the actual callable type that is passed by user during construction.

---

The binding between data and code is done at construction phase at compile time. If we assign a `std::function` variable to another instance, the data and code must be both changed at the same time, which is done during run time (using the `swap(...)` member function). This data and code binding pattern happens for all methods of implementing type erasure:

- **Virtual classes** are bound to their vtable during compile time
- **Statically generated template functions** (or user written functions implementing type erasure) bind data and code at compile time

This data and code binding during compile time is at the core of how type erasure works, since only after the binding, type can be erased.

![std::function Implementation](/assets/images/std_function.png)

The original analysis uses *compile-time binding* for the relationship encoded
between `_Functor` and `_Function_handler<_Functor>`. The compiler instantiates
the matching `_M_invoke` and `_M_manager` functions and hardcodes their
addresses as the operations compatible with that callable type. Construction
then materializes that precompiled relationship in a particular runtime object
by storing the callable and those function pointers together. Assignment moves
or replaces the complete data-and-code bundle so it remains type-compatible.

## The public callable contract

The outer template specialization fixes the interface visible to consumers:

```cpp
std::function<int(int)> operation;
```

Code that invokes `operation` knows the argument and result contract. It does
not need to know whether the stored target is a free function, lambda, bound
member function, or callable class.

```cpp
operation = [](int value) { return value + 1; };
operation = &freeFunction;
operation = CallableObject{};
```

These targets have different concrete C++ types but satisfy the same callable
contract.

## The second template level sees the callable type

`std::function<R(Args...)>` has a templated constructor and assignment
operation. At each binding site, the compiler knows the concrete `Callable`
type and can instantiate an adapter such as this conceptual function:

```cpp
template <typename Callable>
int invoke(void* storage, int argument)
{
    return std::invoke(
        *static_cast<Callable*>(storage),
        argument);
}
```

Every instantiated adapter has a uniform erased signature even though its body
recovers a different `Callable`. Implementations also require callable-specific
operations for destruction, copy, move, and storage management.

Templates therefore supply static polymorphism at the binding edge: they
generate the type-specific code that the erased runtime object will later use.

## Storage, manager, and invoker

A common implementation model contains:

- storage for the callable, either inline or through allocated storage;
- an invoker pointer compatible with `R(Args...)`; and
- manager or lifecycle operations for the concrete callable type.

In libstdc++, concepts such as `_Any_data`, `_M_manager`, `_M_invoker`, and
`_Function_handler<Signature, Callable>` implement this division. These names
and the exact layout are implementation details; the C++ Standard specifies
behavior, not this particular operation-table representation.

The essential invariant is that the stored object and all adapters agree on
the same concrete callable type. Copying, moving, assigning, or destroying a
`std::function` must update or use the storage and its associated operations as
one coherent unit.

## Three distinct phases

The complete mechanism is easier to understand when compile time, construction,
and invocation are kept separate.

### Compile time: generate adapters

When a binding expression supplies `Callable`, the compiler instantiates or
selects callable-specific invocation and lifecycle code. The generated
functions are ordinary machine code in the program or one of its libraries.

### Construction or assignment: bind runtime state

Construction stores the callable and records the matching invoker and lifecycle
operations in the `std::function` object. This is runtime object initialization,
even though the adapter code was generated earlier.

Assignment can replace the target. The object is not permanently bound after
its first construction:

```cpp
std::function<int(int)> operation =
    [](int value) { return value + 1; };

operation =
    [](int value) { return value * 2; };
```

The second assignment replaces both the callable state and the operations that
know how to invoke and manage that state.

### Runtime invocation: follow the stored invoker

`operator()` does not perform overload resolution among callable candidates.
Construction or assignment has already selected the adapter. Invocation passes
the erased storage and arguments through the stored invoker, which recovers the
callable type internally and executes it.

```text
Compile time:
    Callable is known
    -> generate Callable-specific invoke and lifecycle adapters

Construction or assignment:
    store Callable
    -> store the matching adapter pointers

Runtime invocation:
    operator()(arguments)
    -> indirect call through the stored invoker
    -> concrete Callable executes
```

## Consumer-side and binding-side knowledge

The translation unit constructing or assigning the wrapper must know the
concrete callable type. A translation unit that only receives and invokes a
`std::function<R(Args...)>` needs to know only the erased signature.

```text
binding side
    knows Callable
    -> constructs std::function<R(Args...)>

consumer side
    knows only R(Args...)
    -> invokes the stored callable indirectly
```

Concrete callable knowledge has not disappeared from the whole program. Type
erasure confines that knowledge to the adapter-generation and binding site so
the consumer can remain type-independent.

## Relationship to virtual interfaces

This series classifies virtual interfaces operationally as type erasure. A
derived-object construction records a vptr associated with the derived type;
later calls through `Base&` load a vtable slot and invoke the override. The
compiler-generated vtable plays the role of an operation table.

`std::function` follows the same broad storage-plus-operations pattern without
requiring callable types to inherit from a public base. Its templated binding
adapter performs the work that a derived class and compiler-generated virtual
dispatch machinery perform in an inheritance hierarchy.

This terminology is broader than common usage, which often reserves *type
erasure* for wrappers such as `std::function`. The operational classification
is useful here because both designs hide a concrete implementation type behind
a uniform behavioral contract and preserve behavior through an indirect
operation table.

## The hybrid classification

`std::function` combines three mechanisms:

1. **Static polymorphism:** the templated binding operation generates
   callable-specific adapters.
2. **Type erasure:** the resulting public value no longer exposes the callable
   type; it exposes only `R(Args...)`.
3. **Runtime polymorphism:** `operator()` dispatches through the invoker stored
   in that particular object.

The concise model is:

> Templates generate the adapters, construction or assignment binds one
> callable to those adapters, and runtime invocation follows the stored
> invoker.

For type erasure of stored values rather than callables, see
[Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html).

## References

- [Polymorphism, Type Erasure, and std::function](https://shan-weiqiang.github.io/2026/08/23/polymorphism-type-erasure-std-function.html)
- [`function_ref`: a type-erased callable reference — P0792R10](https://www.open-std.org/JTC1/SC22/WG21/docs/papers/2022/p0792r10.html)
- [libstdc++ `bits/std_function.h`](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/bits/std_function.h)

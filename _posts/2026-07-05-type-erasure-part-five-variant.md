---
layout: post
title:  "Closed Tagged Dispatch — std::variant"
date:   2026-07-05 10:00:00 +0800
tags: [cpp, closed-tagged-dispatch, polymorphism]
---

Previously:

- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)
- [Type Erasure II — std::function](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure III — Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)

> **Editor's note:** An earlier version classified `std::variant` as type
> erasure because it combines a runtime tag with generated dispatch machinery.
> This article now follows the more precise taxonomy developed in
> [Polymorphism, Type Erasure, and std::function](https://shan-weiqiang.github.io/2026/08/23/polymorphism-type-erasure-std-function.html):
> `std::variant` is a type-safe union with closed tagged dispatch, not type
> erasure.

`std::variant<Ts...>` provides runtime selection among a set of alternatives
that is completely enumerated in its public C++ type. For example,
`std::variant<int, std::string>` says directly that the value may contain an
`int` or a `std::string`. Runtime state records which alternative is active,
but no alternative has disappeared from the interface.

This makes `std::variant` a form of runtime polymorphism, specifically
**closed tagged dispatch**. It is not type erasure under the definition used in
this series because the consumer-visible type still names the complete set of
concrete alternatives.

* toc
{:toc}

## A type-safe union with a closed alternative set

The WG21 proposal that introduced `std::variant` describes it as a
**type-safe union**. Its template arguments form the closed set of possible
stored types:

```cpp
using Value = std::variant<int, std::string>;

Value value = 42;
// Value still exposes the complete set: int or std::string.
// value.index() == 0, so int is currently active.
```

The static type `Value` exposes both alternatives. Adding `double` requires a
different type, `std::variant<int, std::string, double>`, and recompilation of
code that depends on that type.

This is the decisive distinction from an erased wrapper:

```text
Type-erased interface:
    std::function<int(int)>
    -> public type names the signature, not the callable types

Closed tagged union:
    std::variant<int, std::string>
    -> public type explicitly enumerates every alternative
```

![Virtual type erasure compared with std::variant closed tagged dispatch](/assets/images/type_erasure_virtual_variant_dispatch.png)

## Construction and the active alternative

When code constructs, assigns, or emplaces an alternative, the implementation:

1. Destroys the previous active member when necessary.
2. Constructs the selected `T` in the variant's storage.
3. Records the compile-time-known alternative index as runtime state.

```cpp
Value value = 42;
value.emplace<std::string>("hello");
```

After the `emplace`, the active alternative is `std::string`. A later assignment
may change it again. This is ordinary discriminated-union state, not a permanent
binding to an erased implementation.

## Runtime dispatch through `std::visit`

`std::visit` reads the active alternative and invokes the supplied callable
with the corresponding concrete reference:

```cpp
std::visit(
    [](const auto& item) {
        use(item);
    },
    value);
```

The callable must be valid for every possible alternative. Its concrete type
and the complete `variant<Ts...>` type are known when the call site is compiled.
The compiler therefore instantiates the required handler for each `Ti`.

![std::visit flow: index at runtime, switch or table, get the active alternative, and invoke the visitor](/assets/images/cpp_variant_visit_flow.png)

An implementation may realize this selection with a switch, a jump table, or a
function-pointer table. libstdc++ uses machinery such as `__do_visit` and, for
some cases, generated `__visit_invoke` thunks. These are implementation
techniques. A function table does not by itself make the public abstraction
type-erased.

## The visitor is also not erased

Each distinct `(Visitor, variant<Ts...>)` pair produces its own template
instantiation. Passing two different lambdas creates two statically distinct
operations:

```cpp
std::visit([](const auto& item) { print(item); }, value);
std::visit([](const auto& item) { hash(item); }, value);
```

Runtime chooses the active alternative for one already-compiled operation. It
does not choose among erased visitor implementations. Wrapping a visitor in
`std::function` would add callable erasure, but `std::visit` does not require
that wrapper.

## Closed tagged dispatch versus virtual type erasure

This series classifies a virtual interface operationally as type erasure. A
caller using `Shape&` does not enumerate `Circle`, `Rectangle`, or future
derived types. The compiler-generated vtable is an operation table that
preserves selected behavior after the derived type is hidden.

That terminology is broader than common usage, which often reserves *type
erasure* for wrappers such as `std::function` and `std::any`. The operational
reason for including virtual interfaces is that `Base&` hides the derived type
behind a uniform behavioral contract in the same way an explicit erased
function table does.

`std::variant` differs at the public boundary:

| Property | Virtual interface | `std::variant<Ts...>` |
| --- | --- | --- |
| Runtime-polymorphic selection | Yes | Yes |
| Consumer-visible type | `Base&`; derived types are not enumerated | Every `Ti` is enumerated |
| Runtime state | vptr and selected vtable | active `index()` |
| Dispatch mechanism | vtable slot | switch, jump table, or visit table |
| Extensibility | Open derived-type set | Closed alternative set |
| Type erasure in this taxonomy | Yes | No |

The similar tag-and-dispatch shape is useful for comparing implementations,
but it does not erase the static distinction between an open behavioral
interface and a closed discriminated union.

## Double dispatch on a closed set

`std::variant` and `std::visit` are useful when behavior depends on the active
alternative and the selected operation. The alternative axis is selected at
runtime through `index()`. The operation axis is represented by the concrete
callable at each compiled `std::visit` call site, not by a second runtime
vtable.

See [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html)
for the detailed comparison with the virtual Visitor pattern.

## What this mechanism is not

- **Not type erasure:** the public `variant<Ts...>` type enumerates all
  alternatives.
- **Not runtime typing:** every `Ti` and every visitor branch is known during
  compilation.
- **Not RTTI:** selection uses the variant's discriminant rather than
  `type_info` or `dynamic_cast`.
- **Not callable erasure:** `std::visit` is instantiated for the concrete
  visitor type.

## Summary

- `std::variant<Ts...>` is a type-safe union with a closed compile-time set of
  alternatives.
- Runtime state records which alternative is active, and `std::visit` performs
  closed tagged dispatch to an already-generated handler.
- Switches and function tables are possible dispatch implementations; neither
  one changes the public type into an erased interface.
- Virtual interfaces and `std::function` hide concrete implementation types;
  `std::variant` explicitly lists them.
- `std::variant` demonstrates that runtime polymorphism does not require type
  erasure.

## References

- [Polymorphism, Type Erasure, and std::function](https://shan-weiqiang.github.io/2026/08/23/polymorphism-type-erasure-std-function.html)
- [Variant: a type-safe union for C++17 — P0088R2](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2016/p0088r2.html)
- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure VI — dynamic_cast & RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)
- [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html)
- [libstdc++ `include/std/variant`](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/variant)

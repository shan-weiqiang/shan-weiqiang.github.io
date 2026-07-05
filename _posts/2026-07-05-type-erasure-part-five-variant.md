---
layout: post
title:  "Type Erasure V — std::variant"
date:   2026-07-05 10:00:00 +0800
tags: [data-typing]
---

Previously:

- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)
- [Type Erasure II — std::function](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure III — Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)

[Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) introduced type erasure through virtual inheritance and summarized [`std::variant`](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html#stdvariant) in the same terms. This part develops that summary in full: **`std::variant<Ts...>` is type erasure** — the same core mechanism as virtual inheritance on an inheritance hierarchy: one **interface** at the use site, **runtime tag**, **redirect table**, **binding fixed at construction**. What differs is **encoding**, not the erasure model. The **key difference** from virtual: **closed** alternative set (`variant` lists every `Ti` in the type) vs **open** set (new `Derived` can be added elsewhere).

* toc
{:toc}

## Part I recap: one mechanism

From [Part I — Core logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html):

- Encapsulate type information in the **implementation**; remove it from the **interface** the caller sees.
- **Binding** completes at construction (or compile time for templates).
- **Dispatch** at runtime redirects through **function pointers** (vtable, visit table, or similar).

Virtual inheritance fits this model: call sites hold `Shape&`; the concrete `Circle` or `Rectangle` is hidden until the vtable resolves the override. **`variant<int, string>` fits the same model:** call sites hold `variant<int, string>`; the active `int` or `string` is hidden until `index()` and the redirect table pick the handler.

![Virtual vs variant type erasure: binding at construction sets runtime tag (vtable slot or index), redirect table selects handler for active type](/assets/images/type_erasure_virtual_variant_dispatch.png)

## `variant<Ts...>` as the interface

At a variable declaration you write **`variant<int, std::string>`**, not `int` or `string` separately. That type name **is** the uniform interface — analogous to `Shape&` on an open hierarchy, except the allowed alternatives are **enumerated** in the template parameter pack.

```cpp
std::variant<int, std::string> v = 42;
// Caller type: variant<int, string> — active alternative erased until dispatch.
// v.index() == 0  →  int is live inside the union buffer.
```

Think of `variant<A, B, C>` as the **base type name** and `A`, `B`, `C` as the **alternatives** (like derived types). All are known when you compile. Runtime never adds a fourth type; it only records **which slot is active**.

## Binding at construction

When you write `v = 42` or `v = "hello"` or `v.emplace<std::string>(...)`, the implementation:

1. Destroys the previous active member (if any).
2. Placement-news the new `T` into the union slot for that alternative.
3. Sets `_M_index` to the compile-time-known index of `T`.

After that, binding is fixed until the next assignment — parallel to constructing a `Circle` object whose dynamic type is fixed behind a `Shape&` reference.

## Runtime dispatch: index ≈ vtable tag, table ≈ vtable entries

**Tag:** `index()` (libstdc++: `_M_index`) records which alternative is live — the same *role* as reading which vtable slot / dynamic type applies.

**Table:** `std::visit`, destruction, copy, and move use compile-generated **function-pointer tables** (`__do_visit`, `_S_vtable` of `__visit_invoke` thunks) to jump to the correct `Ti` handler.

```cpp
// libstdc++ — simplified destruction path
std::__do_visit([](auto&& mem) {
  std::_Destroy(std::addressof(mem));
}, __variant_cast<_Types...>(*this));
```

Explicit mapping:

| Virtual (open) | `variant` (closed) |
| --- | --- |
| vptr → vtable | `_M_index` |
| vtable[i] → `Circle::draw` | table[index] → `__visit_invoke` → `f(int&)` or `f(string&)` |
| Binding at `Circle` construction | Binding at `v = 42` or `v = "hi"` |

![std::visit flow: index at runtime, switch or vtable, __get, invoke visitor with concrete T&](/assets/images/cpp_variant_visit_flow.png)

The visit “vtable” is **not** type-erasing your callable — `visit` is a template instantiated for your exact lambda type. The **stored value** is what is erased behind `variant<Ts...>`; the table selects how to reach the active `Ti&`.

## `std::visit` as an operation table

Each **`std::visit(callable, v)`** call site is like a **new visitor derived class**:

- The callable must handle **every** alternative (exhaustive at compile time).
- The library generates a **handler table** for this `(callable, variant<Ts...>)` pair.
- Runtime reads `index()` and invokes the branch for the active `Ti`.

```cpp
std::variant<int, std::string> v = /* ... */;

std::visit([](auto&& x) {
  using T = std::decay_t<decltype(x)>;
  if constexpr (std::is_same_v<T, int>) { /* print */ }
  else { /* print string */ }
}, v);   // one "PrintVisitor" monomorphization

std::visit([](auto&& x) { /* hash */ }, v);  // another operation table
```

Axis 2 of classic [double dispatch](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html) (which operation runs) is realized by **separate call sites** with different callables, not by a second runtime vtable on a shared `Visitor&`. See the [double-dispatch companion post](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html) for libstdc++ internals and comparison with the virtual Visitor pattern.

## The key difference: open vs closed

**Same type-erasure mechanism.** **Different extensibility:**

| | Virtual (**open**) | `variant` (**closed**) |
| --- | --- | --- |
| Who declares alternatives | Base + protocol; **new `Derived` in other TUs/libraries** | **Author lists every `Ti` in `variant<Ts...>`** |
| Call-site interface | `Shape&` — does not enumerate derived types | `variant<A,B,C>` — **enumerates** all allowed types |
| Add a new stored type | New class + (for Visitor) new `visitXxx` on base | Change to e.g. `variant<int, string, double>` + recompile |
| Add a new operation | New `Visitor` subclass | New `std::visit(callable, v)` call site |
| Stored value (open, no inheritance) | — | [`std::any`](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) — manager pointer tag, any copy-constructible `T` |

**Virtual** suits stable protocols where **stored types** grow in plugins (compilers, scene graphs). **`variant`** suits when you **know the full closed set upfront** and want tag+table erasure without inheritance or vtables on the element type.

Neither pattern introduces types at runtime that were absent from the build. Both **select** among compile-time-known alternatives.

## Comparison with Part I virtual erasure

| Concept | Virtual ([Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)) | `variant` (this part) |
| --- | --- | --- |
| Uniform interface | `Shape&`, `Visitor&` | `variant<A,B,C>` |
| Runtime tag | vtable pointer + slot | `index()` |
| Redirect table | vtable | `_S_vtable` / `__do_visit` thunks |
| Binding fixed | object construction | variant construction / assign / `emplace` |
| Alternative set | **Open** | **Closed** |
| Type erasure? | **Yes** | **Yes** — same core |

## What this is not

- **Not RTTI** — no `type_info` or `dynamic_cast`; see [Type Erasure VI — dynamic_cast & RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) for identity recovery on open hierarchies.
- **Not erasing the visit callable** — unless you wrap it in `std::function` yourself; `visit` monomorphizes your lambda type.
- **Not runtime typing** — every `Ti` is listed in `variant<Ts...>` before the program runs.

## Summary

- **`std::variant<Ts...>` is type erasure** — one interface type, active alternative hidden, recovered via **index + function table**, binding at construction.
- **Same mechanism as virtual** — tag (index ≈ vtable slot), table (visit/lifetime thunks ≈ vtable entries), uniform interface at the use site.
- **Key difference: open vs closed** — virtual lets users add `Derived` elsewhere; `variant` requires every possible type in the template list.
- **Each `std::visit(callable, v)`** ≈ a new visitor class with its own handler table, selected by `index()`.
- **Double dispatch** on a closed set: [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html). **Open stored-value erasure:** [Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html). **RTTI recovery on open hierarchies:** [Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html).

## References

- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure VI — dynamic_cast & RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)
- [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html)
- [Double Dispatch and the Visitor Pattern in C++](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html)
- [std::variant — cppreference](https://en.cppreference.com/w/cpp/utility/variant)
- [std::visit — cppreference](https://en.cppreference.com/w/cpp/utility/variant/visit2)
- [libstdc++ `include/std/variant` — GCC mirror](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/variant)

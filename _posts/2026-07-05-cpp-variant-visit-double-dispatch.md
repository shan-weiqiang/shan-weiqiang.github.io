---
layout: post
title:  "Double Dispatch with std::variant and std::visit"
date:   2026-07-05 11:00:00 +0800
tags: [cpp]
---

This post complements [Double Dispatch and the Visitor Pattern in C++](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html). That post uses **virtual** dispatch on **open** class hierarchies (`accept` + `visitCircle`). Here we cover **static** dispatch on a **closed** alternative list via [`std::variant`](https://en.cppreference.com/w/cpp/utility/variant) and [`std::visit`](https://en.cppreference.com/w/cpp/utility/variant/visit2).

Both posts are about **double dispatch** — picking behavior when element type and operation both matter — but the mechanisms diverge: virtual dispatch uses **two runtime vtable hops** on shared bases; `variant`/`visit` uses **one runtime index hop** plus **separate monomorphized call sites** per operation.

**Foundation:** C++ is **statically typed**. A `variant<int, std::string>` does not hold “some unknown type” at runtime — it holds **one of** `int` or `string`, both declared in the type before the program runs. `std::visit` must provide a handler for **every** alternative; if any is missing, the program **does not compile**. Runtime reads `index()` and picks among branches the compiler already generated.

**Same type-erasure mechanism as virtual** — uniform interface (`variant<Ts...>`), runtime tag (`index()`), redirect table (`__do_visit` / `_S_vtable`), binding at construction. The **key encoding difference** is **open vs closed**: virtual lets you add `Derived` elsewhere; `variant` fixes every alternative in `variant<Ts...>`. Full theory: [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html).

* toc
{:toc}

## Static typing: why variant lists every alternative

There is no C++ feature that lets you **use** a type at runtime that was **unknown at compile time**. `std::variant` is often mistaken for “runtime typing,” but it is really **compile-time typing with runtime selection**:

```cpp
std::variant<int, std::string> v = 42;
// The type std::variant<int, std::string> fixes the set {int, string} at compile time.
// v.index() at runtime returns 0 or 1 — it does not discover a third type.
```

| Compile time | Runtime |
| --- | --- |
| Alternatives `int`, `string` appear in `variant<int, string>` | `index()` says which one is **active** |
| Compiler generates storage, dtors, and `visit` thunks for **each** alternative | Only the active alternative’s logic runs |
| `std::visit(f, v)` requires `f` to be callable with **every** `Ti&` | Dispatch picks the matching `Ti` for this `v` |

Adding a new alternative means changing the type to e.g. `variant<int, string, double>` and **recompiling** — the closed set is a compile-time contract, not a runtime discovery.

The same rule applies to [virtual Visitor double dispatch](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html): `Circle`, `Rectangle`, `visitCircle`, and `visitRectangle` are all known when you build; runtime only selects among them. See [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) for the open-hierarchy case with `dynamic_cast`.

## Double dispatch on a closed type set — and how it differs from virtual dispatch

When you call `std::visit(visitor, v)` on `std::variant<int, std::string> v`, **runtime dispatch happens** — **index + table dispatch**, the same type-erasure core as vtable redirection ([Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)). You hold `variant<int, string>` at the use site, not `int&` or `string&`, until dispatch reads `index()` and jumps through the table.

Within **one** `std::visit` call, the library:

1. reads `v.index()` at runtime;
2. jumps through a compile-generated table to the branch for the active alternative;
3. invokes **your** callable with the **concrete** active type (`int&` or `string&`).

That is the only runtime axis inside a single call: **index → which `Ti&` to pass into which overload of this callable**.

![std::visit flow: index at runtime, switch or vtable, __get, invoke visitor with concrete T&](/assets/images/cpp_variant_visit_flow.png)

The **second axis** of classic [virtual double dispatch](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html) — which *operation* / which *Visitor* runs — works very differently here. It is **not** a second runtime vtable lookup on a shared `Visitor` base. It is realized by **different `std::visit` call sites**, each passing a **different callable** that accepts every `Ti` in `variant<Ts...>`:

```cpp
std::variant<int, std::string> v = /* ... */;

// Each callable must accept every alternative (int& and string&):
std::visit([](auto&& x) {
  using T = std::decay_t<decltype(x)>;
  if constexpr (std::is_same_v<T, int>) { /* print int */ }
  else { /* print string */ }
}, v);   // "PrintVisitor" at this call site

std::visit([](auto&& x) {
  using T = std::decay_t<decltype(x)>;
  if constexpr (std::is_same_v<T, int>) { /* hash int */ }
  else { /* hash string */ }
}, v);   // "HashVisitor" at this call site
// same v, different callables → different monomorphized visit specializations
```

Each call is a **unique template instantiation** — determined by the exact callable type and exact `variant<Ts...>` type. The compiler generates separate dispatch machinery per pair. That is like writing a **new derived `Visitor` class** for each operation in the virtual pattern — except the binding is **static at the call site**, not runtime polymorphism on a visitor object.

| Axis | Virtual Visitor | `variant` / `visit` |
| --- | --- | --- |
| **1 — stored / element type** | Runtime: virtual `accept` → `visitCircle(c)` | Runtime: `index()` → invoke with `int&` or `string&` |
| **2 — operation / visitor type** | Runtime: virtual `visitXxx` on a shared `Visitor&` | **Compile time per call site:** each `std::visit(different_callable, v)` is its own monomorphized implementation |
| Uniform interface? | Yes — `Visitor` base, `Shape&` | Yes — `variant<Ts...>` at the use site |
| Type erasure? | **Yes** — `Shape&` / `Visitor&` hide concrete types; vtable dispatch ([Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)) | **Yes** — `variant<Ts...>` hides active alternative; `index()` + table dispatch ([Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)) |
| **Open vs closed** | **Open** — new `Derived` can be added elsewhere | **Closed** — every `Ti` fixed in `variant<Ts...>` |

**Analogy that makes them comparable:** treat each `std::visit(my_callable, v)` as one concrete visitor implementation (like `PrintVisitor : Visitor`). The *intent* of double dispatch — pick behavior by element type **and** by operation — is the same. Both use the **same type-erasure mechanism** (uniform interface, runtime tag, redirect table); the **key difference** is **open vs closed** alternative set.

## What std::variant stores

cppreference defines [`std::variant`](https://en.cppreference.com/w/cpp/utility/variant) as a **type-safe union**: an instance holds a value of **one** of its alternative types, or (rarely) no value ([`valueless_by_exception`](https://en.cppreference.com/w/cpp/utility/variant/valueless_by_exception)). The active object is **nested within** the variant — not heap-allocated separately.

Constraints worth remembering:

- Cannot hold references, arrays, or `void`.
- All alternatives must be destructible.
- The alternative list is **fixed at compile time** in the type signature — this is not negotiable in a statically compiled language.
- [`index()`](https://en.cppreference.com/w/cpp/utility/variant/index) returns the zero-based index of the active alternative; [`variant_npos`](https://en.cppreference.com/w/cpp/utility/variant/variant_npos) marks the invalid state.

The type `std::variant<int, string>` **is** the compile-time manifest of allowed types. Runtime never widens that set.

### Memory model: union + index

Conceptually:

```text
variant<int, string>
  └── storage
        ├── _M_u   union buffer (one of int, string is lifetime-active)
        └── _M_index   0 or 1 at runtime
```

Alternatives are **not** separate live sub-objects side by side. At most one `T` is constructed in the union buffer. Inactive slots are not destroyed — they were never constructed.

### Destruction uses index dispatch

In [libstdc++](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/variant), `_Variant_storage::_M_reset()` destroys only the **active** member:

```cpp
// libstdc++ — simplified
std::__do_visit([](auto&& __this_mem) mutable {
  std::_Destroy(std::__addressof(__this_mem));
}, __variant_cast<_Types...>(*this));
_M_index = variant_npos;
```

Only **`~T` for the active `T`** runs — and `T` is always one of the alternatives the compiler already knew about. The library dispatches by index through the same machinery as `std::visit` — it does not hand-write `if (index==0) … else …`.

![variant destruction flow: ~variant, _M_reset, __do_visit, index dispatch, _Destroy of active T](/assets/images/cpp_variant_destruction_flow.png)

Copy, move, and assignment reuse **`__raw_idx_visit`** — the same index-driven dispatch for every special member function. Construction placement-news the **real** `T_N` into slot `N`; destruction calls the **real** `~T` for the active member only. Lifetime uses the same tag+table erasure core as `std::visit`.

## Index + table dispatch (type erasure)

`std::variant` / `std::visit` use the **same type-erasure core** as virtual dispatch — uniform interface, runtime tag, redirect table, binding at construction. See [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) for the full treatment. What differs is **encoding** and **open vs closed**:

| | Virtual ([Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)) | `variant` / `visit` ([Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)) |
| --- | --- | --- |
| Type erasure? | **Yes** | **Yes** |
| **Open vs closed** | **Open** — new `Derived` elsewhere | **Closed** — every `Ti` in `variant<Ts...>` |
| Runtime tag | vtable pointer + slot | `index()` |
| Redirect table | vtable | `_S_vtable` / `__do_visit` thunks |
| Callable in `visit` | N/A | **Not** erased — monomorphized per call site (contrast `std::function`) |
| Compiler output | One interface type; concrete types behind vtable | Monomorphized per `Ti` and per callable; tag+table for axis 1 |

Both hide the active concrete type at the use site until dispatch. Virtual uses vtable encoding on an **open** hierarchy; `variant` uses index + function table on a **closed** list.

### What the compiler generates (all concrete)

For `std::variant<int, float, std::string>`, the implementation is fully specialized at compile time:

- **Storage** — `_Variadic_union<int, float, string>` with `_M_index`.
- **Construction** — `in_place_index<N>` → placement-new of the **actual** `T_N`.
- **Destruction / copy / move / assign** — `__do_visit` / `__raw_idx_visit` thunks that call `_Destroy`, `_Construct`, etc. on the **concrete** active `T&`.
- **`std::visit(f, v)`** — a function **template** instantiated for your exact `f`; `__visit_invoke` calls `std::__invoke(f, concrete_T&...)`.

Nothing in that pipeline forgets which `Ti` or which visitor type you passed. The function-pointer table libstdc++ builds (`_S_vtable` of `__visit_invoke` thunks) dispatches **index → call visitor with `int&` vs `string&`**. It does **not** erase your lambda into a generic callable the way `std::function` does.

```text
Virtual:       Shape& → (vtable tag) → vtable → concrete override
variant/visit: variant<Ts...> → (index tag) → table → concrete Ti handler
```

Both erase the active type at the use site; `index()` ≈ vtable tag, function table ≈ vtable entries.

### Each `std::visit` call is a unique instantiation

`std::visit` is a function template. Every distinct pair `(Visitor, variant<Ts...>)` at a call site gets its own generated dispatcher — index table, thunks, and overload checks included:

```cpp
std::visit([](auto&& x) { /* A */ }, v);              // instantiation 1
std::visit([](auto&& x) { /* B */ }, v);              // instantiation 2 (different Visitor)
std::visit(f, std::variant<int, float>{});            // instantiation 3 (different Ts...)
```

Nothing is shared through a type-erased `std::function`-like interface unless **you** wrap the callable that way. The runtime half is always the same within one instantiation: read `index()`, call the matching branch of **this** callable.

Callables can be lambdas, function objects, function pointers, or `std::function` in an overload set — `visit` accepts any type that is invocable with every alternative. The template argument is always the **concrete** callable type you pass in.


## std::visit vs classic Visitor pattern

Your handlers in `std::visit` are **not** virtual methods on a `Visitor` base class. They are **static overloads** or a generic lambda with `if constexpr` — each branch is **typed at compile time**, invoked through a library-generated thunk at runtime.

| | Classic Visitor | `std::visit` |
| --- | --- | --- |
| All types known when? | **Compile time** (`Circle`, `visitCircle`, …) | **Compile time** (`variant<Ts...>`, each overload) |
| Goal | Different operation per concrete type | Same |
| Visitor API | Virtual `visitCircle`, `visitRectangle` on one `Visitor` base | **No base class** — each operation = new callable at new call site |
| Dispatch axis 1 (element) | Runtime virtual `accept` on element | Runtime `index()` → `Ti&` |
| Dispatch axis 2 (operation) | Runtime virtual `visitXxx` on visitor object | **Compile time:** separate `std::visit(callable, v)` per operation |
| Uniform signature? | `Visitor&` + `Shape&` | `variant<Ts...>` at use site; callable monomorphized per call site |
| Library "vtable" | User-defined on element + visitor | `_S_vtable` of `__visit_invoke` thunks (axis 1 only) |

```text
Classic:  shape.accept(visitor)     →  2 runtime vtables (element + visitor)
visit:    std::visit(callable, v)     →  1 runtime index dispatch + callable fixed at call site
          std::visit(other_callable, v)  →  separate monomorphization ≈ new Visitor subclass
```

Both pursue **double dispatch in intent** (element tag + operation). Virtual dispatch runs **both** selections at runtime through shared bases (`Shape&`, `Visitor&`) and vtables. `std::visit` runs **one** runtime selection (`index()`); the operation dimension is **which call site / which callable you compiled**. Both use the **same type-erasure mechanism**; the **key difference** is **open vs closed** ([Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)).


## Summary

- **Same type-erasure mechanism:** uniform interface, runtime tag, redirect table, binding at construction — for both virtual and `variant`/`visit`.
- **Key difference: open vs closed** — virtual: user can implement new `Derived` elsewhere; `variant`: author must list all possible types in `variant<Ts...>`.
- Each **`std::visit(callable, v)`** ≈ a new visitor derived class with its own handler table; runtime reads `index()` and jumps to the matching branch within that instantiation.
- **Double dispatch axis 2** differs in encoding: virtual uses a second runtime vtable on `Visitor&`; `variant` uses separate monomorphized call sites per operation.
- Details: [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) (type erasure); [Double Dispatch and the Visitor Pattern](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html) (virtual double dispatch); RTTI in [Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html).

## References

- [std::variant — cppreference](https://en.cppreference.com/w/cpp/utility/variant)
- [std::visit — cppreference](https://en.cppreference.com/w/cpp/utility/variant/visit2)
- [libstdc++ `include/std/variant` — GCC mirror](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/variant)
- [Double Dispatch and the Visitor Pattern in C++](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html)
- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) (fn-ptr dispatch vocabulary)
- [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) (type erasure theory)
- [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) (open hierarchy, RTTI recovery)

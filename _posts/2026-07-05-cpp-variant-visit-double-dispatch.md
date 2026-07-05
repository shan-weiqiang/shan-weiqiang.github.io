---
layout: post
title:  "Double Dispatch with std::variant and std::visit"
date:   2026-07-05 10:00:00 +0800
tags: [cpp]
---

This post complements [Double Dispatch and the Visitor Pattern in C++](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html). That post uses **virtual** dispatch on **open** class hierarchies (`accept` + `visitCircle`). Here we cover **static** dispatch on a **closed** alternative list via [`std::variant`](https://en.cppreference.com/w/cpp/utility/variant) and [`std::visit`](https://en.cppreference.com/w/cpp/utility/variant/visit2).

Both posts are about **double dispatch** — picking behavior when element type and operation both matter — but the mechanisms diverge: virtual dispatch uses **two runtime vtable hops** on shared bases; `variant`/`visit` uses **one runtime index hop** plus **separate monomorphized call sites** per operation.

**Foundation:** C++ is **statically typed**. A `variant<int, std::string>` does not hold “some unknown type” at runtime — it holds **one of** `int` or `string`, both declared in the type before the program runs. `std::visit` must provide a handler for **every** alternative; if any is missing, the program **does not compile**. Runtime reads `index()` and picks among branches the compiler already generated.

**Not type erasure:** `variant` and `visit` implement **double dispatch by index** — union storage plus an active-index tag, then a compile-generated branch table. Every alternative’s ctor, dtor, and visit thunk is instantiated as a **concrete** `Ti`; nothing is erased behind a single runtime-polymorphic interface like [`std::function`](https://en.cppreference.com/w/cpp/utility/functional/function) or the wrappers in [Type Erasure Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html). That distinction is the key to understanding every `variant` / `visit` usage.

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

The same rule applies to [virtual Visitor double dispatch](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html): `Circle`, `Rectangle`, `visitCircle`, and `visitRectangle` are all known when you build; runtime only selects among them. See [Type Erasure Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-dynamic-cast-rtti.html) for the open-hierarchy case with `dynamic_cast`.

## Double dispatch on a closed type set — and how it differs from virtual dispatch

When you call `std::visit(visitor, v)` on `std::variant<int, std::string> v`, **runtime dispatch happens** — but it is **index dispatch**, not type erasure. There is no uniform signature (like `Base&` or `operator()`) hiding different concrete implementations behind one interface.

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
| Uniform interface? | Yes — `Visitor` base, `Shape&` | **No** — no erased signature; callable type is explicit in each instantiation |
| Type erasure? | **Yes** — `Shape&` / `Visitor&` hide concrete types; vtable dispatch ([Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)) | **No** — concrete `Ti` and concrete callable type in each `visit` instantiation |

**Analogy that makes them comparable:** treat each `std::visit(my_callable, v)` as one concrete visitor implementation (like `PrintVisitor : Visitor`). The *intent* of double dispatch — pick behavior by element type **and** by operation — is the same. But the mechanism behind is totally different.

**Virtual Visitor erases type at the call site; `variant`/`visit` does not.** [Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html) treats virtual inheritance as a form of type erasure: call sites hold `Shape&` / `Visitor&`, and the vtable recovers the concrete override at runtime. `variant`/`visit` keep every `Ti` and every callable type in the monomorphized code — runtime only uses `index()` to choose **which compile-time-known branch** of **this** instantiation to run.

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

Copy, move, and assignment reuse **`__raw_idx_visit`** — the same index-driven dispatch for every special member function. Construction placement-news the **real** `T_N` into slot `N`; destruction calls the **real** `~T` for the active member only. Lifetime is index dispatch on concrete types, not a type-erased factory.

## Index dispatch, not type erasure

`std::variant` / `std::visit` are often grouped with “type erasure” because they store different types behind one object and use function-pointer tables at runtime. The mechanism is different:

| | Type erasure / virtual ([Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)) | `variant` / `visit` |
| --- | --- | --- |
| Allowed types | Open hierarchy; concrete type hidden at `Base&` call site | **Closed list** in `variant<Ts...>` |
| What runtime selects | Which **vtable** / erased object | Which **index** into `{T1…Tn}` is active |
| Ctor / dtor | Virtual or fn-ptr on **one erased interface** | Real **`Ti` ctor/dtor** at compile-known slot `i` |
| Callable in `visit` | N/A | **Not** erased — `Visitor` is a template parameter |
| Compiler output | One interface type; concrete types behind vtable | **Monomorphized** per `Ti` and per callable |

[Type Erasure Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html) hides concrete type at the call site (`void*`, `Base&`, vtable) — virtual Visitor is in this camp. `variant<int, string>` **lists** its alternatives in the type name; `std::visit` monomorphizes each callable. That is **tagged union + index dispatch**, not erased behavior.

### What the compiler generates (all concrete)

For `std::variant<int, float, std::string>`, the implementation is fully specialized at compile time:

- **Storage** — `_Variadic_union<int, float, string>` with `_M_index`.
- **Construction** — `in_place_index<N>` → placement-new of the **actual** `T_N`.
- **Destruction / copy / move / assign** — `__do_visit` / `__raw_idx_visit` thunks that call `_Destroy`, `_Construct`, etc. on the **concrete** active `T&`.
- **`std::visit(f, v)`** — a function **template** instantiated for your exact `f`; `__visit_invoke` calls `std::__invoke(f, concrete_T&...)`.

Nothing in that pipeline forgets which `Ti` or which visitor type you passed. The function-pointer table libstdc++ builds (`_S_vtable` of `__visit_invoke` thunks) dispatches **index → call visitor with `int&` vs `string&`**. It does **not** erase your lambda into a generic callable the way `std::function` does.

```text
Type erasure:  interface → (vtable) → forgotten concrete type
variant/visit: variant<Ts...> + index → (index table) → known concrete Ti or Visitor
```

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
| Uniform signature? | `Visitor&` + `Shape&` | **No** — monomorphized per `(Visitor, variant<Ts...>)` |
| Library "vtable" | User-defined on element + visitor | `_S_vtable` of `__visit_invoke` thunks (axis 1 only) |

```text
Classic:  shape.accept(visitor)     →  2 runtime vtables (element + visitor)
visit:    std::visit(callable, v)     →  1 runtime index dispatch + callable fixed at call site
          std::visit(other_callable, v)  →  separate monomorphization ≈ new Visitor subclass
```

Both pursue **double dispatch in intent** (element tag + operation). Virtual dispatch runs **both** selections at runtime through **type-erased** shared bases (`Shape&`, `Visitor&`) and vtables. `std::visit` runs **one** runtime selection (`index()`); the operation dimension is **which call site / which callable you compiled**. Virtual Visitor **is** type erasure ([Part I](https://shan-weiqiang.github.io/2025/04/20-type-erasure.html)); `variant`/`visit` is index dispatch on a closed, monomorphized type list.


## Summary

**Key findings:**

- **`std::variant` / `std::visit` use dispatch; they do not use type erasure.** No uniform `Base&` interface — every `Ti` and every callable type stays concrete in the generated code.
- **Virtual Visitor double dispatch does use type erasure** — `Shape&` and `Visitor&` at call sites, vtable recovery at runtime ([Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)).
- **Each `std::visit` call is unique** — monomorphized from the exact callable and exact `variant<Ts...>` passed in. Runtime reads `index()` and jumps to the matching branch **within that instantiation**.
- **“Double dispatch” is not the same as virtual double dispatch.** Axis 1 (which alternative is stored) is runtime index dispatch, comparable to virtual `accept`. Axis 2 (which operation runs) is **not** a second runtime vtable on a visitor object — it is **separate call sites** with **different callables**, like writing a new derived `Visitor` class per operation but bound statically at each call.
- **Comparable intent, different mechanism:** if you treat each `std::visit(my_callable, v)` as one visitor implementation, the patterns align on *what* they achieve; they diverge on *how* the operation axis is selected (runtime virtual vs compile-time call-site monomorphization) and on axis 1 (vtable slot vs `index()`).

## References

- [std::variant — cppreference](https://en.cppreference.com/w/cpp/utility/variant)
- [std::visit — cppreference](https://en.cppreference.com/w/cpp/utility/variant/visit2)
- [libstdc++ `include/std/variant` — GCC mirror](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/variant)
- [Double Dispatch and the Visitor Pattern in C++](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html)
- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) (fn-ptr dispatch vocabulary)
- [Type Erasure: Part V — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-dynamic-cast-rtti.html) (open hierarchy contrast)

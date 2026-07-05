---
layout: post
title:  "Type Erasure: Part VII — std::any"
date:   2026-07-05 13:00:00 +0800
tags: [data-typing]
---

Previously:

- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure Part Two: How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure Part Three: Downsides and Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure Part Four: ROS 2 Message Type System](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)
- [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
- [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)

[Part II](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html) showed type erasure of **callables** via `std::function` — `_M_manager` and `_M_invoker` hide the concrete lambda or function object behind one signature. [Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) showed erasure of a **closed** stored-value set via `std::variant<Ts...>`. This part covers **[`std::any`](https://en.cppreference.com/w/cpp/utility/any)** — **open-set** erasure of **stored values**: one public type name at the call site, any copy-constructible `T` at each construction, recovered later via `any_cast`.

* toc
{:toc}

## Part I recap: same signature, bound at construction

From [Part I — Core logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html):

- Encapsulate type information in the **implementation**; remove it from the **interface** the caller sees.
- **Binding** completes at construction — after that, dispatch is fixed.
- **Dispatch** redirects through **function pointers of the same signature**.

`std::any` follows this model exactly. The public API always speaks `std::any`; construction binds a type-specific **manager** function; every later lifetime operation calls that manager through one unified function-pointer type.

## `std::any` as the interface

```cpp
std::any a = 42;
a = std::string{"hi"};
// Call sites only ever name std::any — not int, not string.
```

Unlike `variant<int, string>`, `any` does **not** enumerate allowed types in its name. Each assignment can store a **different** copy-constructible type. The active type is hidden until you `any_cast` — or until you compare manager addresses inside the library.

## How erasure is achieved: two layers

| Layer | Who sees it | Signatures | Knows stored `T`? |
| --- | --- | --- | --- |
| **Public `std::any` API** | Call sites, `vector<any>`, function parameters | Fixed: `any()`, `any(T&&)`, `~any()`, copy/move, `reset()`, `emplace<>` | **No** |
| **`_Manager_internal<T>` / `_Manager_external<T>`** | libstdc++ header (instantiated per `T` at bind site) | Per-`T` `_S_create`, `_S_manage`, `_S_access` | **Yes** |

You write `any a = my_circle;` once. Every subsequent operation on `a` uses the **same** `any` member signatures. Whether a `Circle`, `int`, or `string` lives inside is invisible until recovery.

```text
Public any API          Erased object              Per-T _Manager<T>
~any reset copy move    _M_manager + _M_storage    _S_create _S_manage _S_access
fixed signatures        same layout always         generated at bind site
```

![std::any type erasure: constructor binds manager pointer, unified _M_manager dispatches destroy clone move, per-T impl hidden in _Manager T](/assets/images/type_erasure_any_dispatch.png)

## Binding at construction — where erasure completes

When you write `any a = Circle{...};`, the compiler instantiates the converting constructor template **once for `Circle`**:

```cpp
// libstdc++ — simplified
template<typename _Tp, typename _VTp = decay_t<_Tp>,
         typename _Mgr = _Manager<_VTp>, ...>
any(_Tp&& __value)
  : _M_manager(&_Mgr::_S_manage)   // (1) bind manager — the type tag
{
  _Mgr::_S_create(_M_storage, std::forward<_Tp>(__value));  // (2) real T ctor
}
```

Step by step:

1. **`_Manager<Circle>` is chosen at compile time** — picks `_Manager_internal<Circle>` (small buffer) or `_Manager_external<Circle>` (heap) from size, alignment, and `is_nothrow_move_constructible`.
2. **`_M_manager = &_Manager<Circle>::_S_manage`** — after this initializer, runtime identity is fixed; all later ops go through that one function address.
3. **`_S_create` runs the real constructor** — placement-new of `Circle` into `_M_buffer`, or `new Circle(...)` stored in `_M_ptr`. The **`any` constructor body never names `Circle`**.

When the constructor returns, the caller holds an `any`. **Binding is complete; the stored type is erased at the interface.**

Empty `any` has `_M_manager == nullptr`; `has_value()` is false.

## Unified lifetime: destructor, copy, move

Public members never branch on “is it an `int` or a `string`?” They always call `_M_manager` with an **opcode**. The switch that knows `T` lives inside `_S_manage`, monomorphized per type at the site that first constructed that `any`.

### Destructor and `reset`

```cpp
~any() { reset(); }

void reset() noexcept {
  if (has_value()) {
    _M_manager(_Op_destroy, this, nullptr);
    _M_manager = nullptr;
  }
}
```

Inside `_Manager_internal<Circle>::_S_manage` for `_Op_destroy`:

```cpp
case _Op_destroy:
  __ptr->~Circle();   // only here does ~Circle run
  break;
```

`~any()` has a **single signature** and **one code path**. The contained type's destructor lives in the type-specific `_S_manage`, reached only via `_M_manager` — parallel to virtual `~Base()` dispatching to `~Derived()`, without an inheritance hierarchy.

### Copy and move

| Operation | Public `any` API (fixed) | Dispatch | Type-specific work |
| --- | --- | --- | --- |
| Copy ctor | `any(const any& other)` | `_M_manager(_Op_clone, &other, &arg)` | copy- or placement-new `T` in destination |
| Move ctor | `any(any&& other)` | `_M_manager(_Op_xfer, &other, &arg)` | move-construct `T`, destroy source, clear source `_M_manager` |
| `operator=(T&&)` | builds temporary `any`, move-assigns | reset old + bind new manager | destroy old `T`, construct new |

Copy constructor (simplified):

```cpp
any(const any& __other) {
  if (__other.has_value()) {
    _Arg __arg;
    __arg._M_any = this;
    __other._M_manager(_Op_clone, &__other, &__arg);
  } else {
    _M_manager = nullptr;
  }
}
```

`_Op_clone` in `_Manager_internal<T>::_S_manage` placement-news a copy of `T` into the destination buffer and copies the manager pointer. **`any`'s copy ctor contains no `T`-specific logic.**

## The manager's unified signature

Every stored type shares one function-pointer **type**:

```cpp
enum _Op { _Op_access, _Op_get_type_info, _Op_clone, _Op_destroy, _Op_xfer };

void (*_M_manager)(_Op, const any*, _Arg*);
```

Each `T` gets its own **`_S_manage` function** with that signature but a body that knows `T`. This is [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)'s dispatch rule: *redirection of function pointers, with the same signature.*

| Mechanism | What is erased | Tag | Lifetime dispatch |
| --- | --- | --- | --- |
| Virtual | `Derived` behind `Base&` | vtable pointer + slot | virtual dtor, copy (if defined) |
| [`std::function`](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html) | callable type | `_M_manager` + `_M_invoker` | `_M_manager` opcodes |
| **`std::any`** | stored value type | `_M_manager` address | `_M_manager` opcodes |
| [`std::variant`](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) | active alternative | `index()` | `__do_visit` / visit table |

**Why one function + opcodes (not a vtable)?** libstdc++ keeps `any` compact — typically **16 bytes** on 64-bit: one manager pointer plus a storage word/buffer. Move, copy, and destroy always need at least one indirect call; a single `_S_manage` with opcodes avoids a second pointer while preserving the unified-signature pattern.

## End-to-end trace

```cpp
std::any x = 42;
// Bind _Manager<int>, SBO: placement-new int in _M_buffer.
// _M_manager = &_Manager<int>::_S_manage

x = std::string{"hi"};
// operator=(T&&) → any(std::string{...}) temporary
//   reset on x: _M_manager(_Op_destroy) → ~int
//   bind _Manager<string>, construct string
// move-assign transfers _M_manager + storage

std::any y = x;
// y's copy ctor: x._M_manager(_Op_clone, &x, &arg)
//   placement-new copy of string in y._M_buffer

// ~y, ~x: each _Op_destroy on string / empty
```

At no point does generic `any` code contain `if (stored int) … else if (stored string)`. Each object's `_M_manager` already points at the correct monomorphized handler.

## Storage: small-buffer vs heap

Object layout (libstdc++):

```text
std::any
  _M_manager   void (*)(_Op, const any*, _Arg*)
  _M_storage   union { void* _M_ptr; unsigned char _M_buffer[sizeof(void*)]; }
```

**`_Manager_internal<T>`** (SBO) when `sizeof(T) <= sizeof(_Storage)`, `alignof(T) <= alignof(_Storage)`, and `is_nothrow_move_constructible_v<T>`:

```cpp
static void _S_create(_Storage& __storage, _Up&& __value) {
  void* __addr = &__storage._M_buffer;
  ::new (__addr) _Tp(std::forward<_Up>(__value));
}
```

**`_Manager_external<T>`** otherwise — `__storage._M_ptr = new _Tp(...)`.

Same small-object idea as [`std::function`](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html): avoid heap allocation for tiny, nothrow-movable types.

## `any_cast` and the type tag

Recovery at the call site names `T` in the **cast**, not in the container type:

```cpp
auto& s = std::any_cast<std::string&>(x);
```

libstdc++ `__any_caster<T>`:

1. **Primary (works without RTTI):** compare `_M_manager == &any::_Manager<U>::_S_manage` — **function pointer equality as type tag**.
2. **Fallback (when `__cpp_rtti`):** `__any->type() == typeid(T)`.

Then `_Manager<U>::_S_access(_M_storage)` returns `T*`. Mismatch throws [`bad_any_cast`](https://en.cppreference.com/w/cpp/utility/any/bad_any_cast).

[`any::type()`](https://en.cppreference.com/w/cpp/utility/any/type) uses `_Op_get_type_info` when RTTI is enabled — links to [Part VI — RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html). The **primary** cast path does not need `type_info`; the manager address **is** the tag.

Contrast [Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html): `variant` uses **`index()`** into a **closed** table; `any` uses **manager address** into an **open** per-`T` handler generated at each construction site.

## Comparing two `std::any` objects

`std::any` provides **no** `operator==` (C++17 through C++26). Binding hides the stored type from **lifetime** APIs (`~any`, copy, move); it does **not** install a type-erased **value comparison** — there is no second function-pointer table analogous to `std::function`'s `_M_invoker`. Comparing two `any`s is a **two-step** problem you implement explicitly: **same type?** then **same value?**

### Each object carries its own tag

After construction, `a` and `b` bind independently:

```text
any a = 42;                    any b = std::string{"hi"};
_M_manager → &_Manager<int>::…  _M_manager → &_Manager<string>::…
_M_storage → [ int ]             _M_storage → [ string ]
```

The manager address is **per type `T` in the program**, not per instance — two `any`s both holding `int` share the **same** `_M_manager` value. Nothing links `a` and `b` automatically; you compare their tags yourself.

### Step 1 — compare types

Use the public observer when RTTI is available:

```cpp
if (!a.has_value() && !b.has_value())
  ; // both empty — equivalent state
else if (a.type() == b.type())
  ; // same stored type (check has_value separately for empty)
```

`a.type() == b.type()` compares **`type_info` identity** ([Part VI — RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)) — same mechanism `any_cast` uses as fallback. Empty `any` reports `typeid(void)`; two empty anys have matching types.

Without RTTI at the call site, the implementation still compares **manager pointers** inside `any_cast`; for two anys you could compare `has_value()` and rely on casting (below), but **`type()` is the portable public API** when enabled.

### Step 2 — compare values (you name `T`)

`any_cast` inspects **one** `any` at a time — it checks whether **that** object's tag matches the `T` you named. It does not look at a second operand.

```cpp
// Known both hold int (types matched above):
if (std::any_cast<int>(a) == std::any_cast<int>(b)) { /* ... */ }

// Safer — pointer overload, no exception:
if (const int* pa = std::any_cast<int>(&a))
  if (const int* pb = std::any_cast<int>(&b))
    if (*pa == *pb) { /* ... */ }
```

You must **name `T` at the call site** — the same static typing rule as everywhere else in C++. If you do not know which `T` might be stored, there is no single library helper: try a chain of `any_cast` attempts, a visitor, or use **`variant<Ts...>`** when the set is closed ([Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)).

### What erasure does and does not hide

| Question | Mechanism | Needs `T` at call site? |
| --- | --- | --- |
| Same stored type in `a` and `b`? | `a.type() == b.type()` (or equal `_M_manager`) | **No** |
| Equal contained values? | `any_cast<T>(a)` vs `any_cast<T>(b)` after type match | **Yes** |
| Destroy / copy / move one `any`? | `_M_manager(_Op_…)` | **No** |

Lifetime stays fully erased behind the unified manager signature. **Value equality** is deliberately **not** erased — unlike `std::function`, which adds `_M_invoker` to call through a fixed signature, `std::any` stops at storage and recovery.

## Open vs closed spectrum

| | Virtual | **`std::any`** | `std::variant` | `std::function` |
| --- | --- | --- | --- | --- |
| What is erased | `Derived` type | **stored value type** | active alternative | callable type |
| Open vs closed | **Open** (inheritance) | **Open** (any copy-constructible `T`) | **Closed** (`variant<Ts...>`) | **Open** (any matching callable) |
| Runtime tag | vtable | **`_M_manager` address** | `index()` | `_M_manager` + `_M_invoker` |
| Recovery | `dynamic_cast` / virtual call | **`any_cast`** | `std::visit` / `get` | `operator()` |

`std::any` is the value counterpart to `std::function`: Part II erases **behavior** (call signature fixed); Part VII erases **payload** (no call — storage and lifetime only).

## Trade-offs

- **Copy-only contents** — `T` must be copy-constructible; no `any` of references or arrays ([cppreference constraints](https://en.cppreference.com/w/cpp/utility/any)).
- **Heap fallback** — large or throwing-move types allocate; SBO is an optimization, not a guarantee.
- **`type()` needs RTTI** — when disabled, rely on manager-pointer equality for `any_cast`.
- **No visitation protocol** — unlike `variant`/`visit` or virtual Visitor; you recover with `any_cast` or compare `type()`. No `operator==` on two `any`s — see [Comparing two `std::any` objects](#comparing-two-stdany-objects).

See [Part III — Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html) for general type-erasure costs.

## Summary

- **`std::any` is type erasure** — uniform public interface, binding at construction, dispatch through **`_M_manager`** with unified signature and type-specific `_S_manage` body.
- **Two layers** — call sites see fixed `any` signatures; per-`T` `_Manager<T>` hides ctor, dtor, copy, and move behind opcodes.
- **Constructor binds** `_M_manager = &_Manager<T>::_S_manage` and `_S_create`; after return, stored type is erased at the interface.
- **`~any` / copy / move** never branch on stored type; they call `_M_manager(_Op_destroy | _Op_clone | _Op_xfer, …)`.
- **Open set** — any copy-constructible `T` per construction; contrast closed `variant<Ts...>` in [Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html).
- **No built-in value comparison** — no `operator==`; compare types via `type()`, then values via `any_cast<T>` after naming `T`.
- **Same manager pattern as Part II** — but erases **value**, not callable; recovery via **`any_cast`** (manager address ≈ tag).
- **Series synthesis:** [Part VIII — Final Thoughts](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-eight-final-thoughts.html).

## References

- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure: Part II — How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
- [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure: Part VIII — Final Thoughts](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-eight-final-thoughts.html)
- [std::any — cppreference](https://en.cppreference.com/w/cpp/utility/any)
- [std::any_cast — cppreference](https://en.cppreference.com/w/cpp/utility/any/any_cast)
- [libstdc++ `include/std/any` — GCC mirror](https://github.com/gcc-mirror/gcc/blob/master/libstdc++-v3/include/std/any)

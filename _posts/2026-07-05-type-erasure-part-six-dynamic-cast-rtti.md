---
layout: post
title:  "Type Erasure: Part VI — dynamic_cast and RTTI"
date:   2026-07-05 12:00:00 +0800
tags: [data-typing]
---

Previously:

- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure Part Two: How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure Part Three: Downsides and Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure Part Four: ROS 2 Message Type System](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)
- [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
- [Type Erasure: Part VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)

In [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) I described type erasure as hiding concrete type information behind a uniform interface, with runtime dispatch redirecting through function pointers of the **same signature**. Virtual dispatch and `std::function` fit that model. [Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) shows the same mechanism on a **closed** alternative list: `variant<Ts...>`, `index()` as tag, visit/lifetime tables as redirect. This part covers a **different** runtime mechanism: **RTTI** and **`dynamic_cast`**, where dispatch is keyed by **type identity** rather than by a pre-planned behavior slot.

One rule underlies all of this — virtual dispatch, type erasure, RTTI, and (in the companion [variant post](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html)) `std::variant`:

> **C++ is statically typed.** If your program can *use* a type, that type must be **known at compile time**. Runtime never introduces a type the compiler did not already generate code for. Runtime only **selects among** compile-time-known alternatives.

* toc
{:toc}

## The static typing rule

This sounds obvious, but it is easy to misread **runtime polymorphism** as “the type is unknown until runtime.” That is not what happens in C++.

| What varies at runtime | What is fixed at compile time |
| --- | --- |
| Which **override** runs (`Circle::draw` vs `Rectangle::draw`) | `Shape`, `Circle`, `Rectangle`, and `virtual draw()` all declared in source |
| Whether `dynamic_cast<Circle*>` succeeds | The name **`Circle`** in the cast; code for `Circle` compiled into the binary |
| Which **alternative** is active in a `variant` | Every member of `variant<int, string, …>` listed in the type |

There is **no** path where you use a type at runtime that was **not** known when the program was compiled. Deferred binding (Parts I–IV) means: *which implementation runs* is decided later — not that *new types* appear later.

**Implication for RTTI:** `dynamic_cast<Derived*>` does not “discover” `Derived` at runtime. You **named** `Derived` in source; the compiler emitted `type_info` and hierarchy metadata for it. Runtime only **checks** whether the object’s dynamic type matches that **already-known** `Derived`.

**Implication for virtual dispatch:** inheritance abstracts **call sites** to `Base&`, but `Base`, every `Derived`, and every virtual override are still **authored and compiled** before run. The vtable holds pointers to functions that already exist in the text segment.

RTTI and virtual dispatch look like opposites — one hides derived types behind `Base*`, one recovers `Derived*` — but both obey the same static rule: **every type in the game is fixed at compile time.** They differ in what the **call site** is allowed to name and what runtime **selects**.

## Dispatch by type identity, not by behavior slot

Part I dispatch picks among implementations that share one interface:

- Virtual call: `base->draw()` → vtable slot → `Circle::draw` or `Rectangle::draw` — **same signature**, behavior declared on the base.
- Type-erased function pointer: `compare(void*, void*)` → `less` or `more` — **same signature**, bound at construction.

`dynamic_cast` introduces a **different** runtime decision:

- The branch is keyed by **`type_info`** (runtime type identity), not by a vtable behavior slot.
- The branch **names** are fixed at compile time (`dynamic_cast<Circle*>`), but which branch runs is decided at runtime.
- After a successful cast, the caller may use the **full derived API** — virtual or not, with **different signatures per branch**.

Conceptually:

```cpp
// Not literal generated code — illustrates the decision shape
if (object.type_info == typeid(Circle)) {
  // full Circle API, including non-virtual radius()
} else if (object.type_info == typeid(Rectangle)) {
  // completely different methods
}
```

Dispatch is still runtime, but it is **not** "pick among function pointers with the same signature."

![Part I virtual dispatch vs Part VI RTTI dispatch: vtable behavior slot compared to type_info check](/assets/images/type_erasure_part_v_dispatch.png)

Closed-set **type erasure** with `std::variant` and `std::visit` uses the same tag+table core as virtual dispatch — see [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) and [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/05/cpp-variant-visit-double-dispatch.html). **Open-set value erasure** with [`std::any`](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) uses a **manager function pointer** as tag; `any_cast` compares that address (primary path), with `type_info` as RTTI fallback — see Part VII. **RTTI** (this part) is different: recovery by **`type_info`** on polymorphic hierarchies, not by manager address or variant index.

## Theory behind RTTI

### What the compiler stores

A class with at least one **virtual** function is **polymorphic**. For such types the compiler typically:

1. Emits one **`type_info`** object per polymorphic type (stable address for the program lifetime).
2. Attaches a **vtable** to the class; on common ABIs (Itanium) the vtable holds a pointer to `type_info` (often at index `-1`).
3. Places a **vptr** in each polymorphic object pointing at that vtable.

Binding of which branches exist (`dynamic_cast<Circle*>`, `dynamic_cast<Rectangle*>`) is fixed when you write the source. The **choice** among them happens at runtime — but only among types the compiler already knows.

RTTI metadata lives on the **vtable** because polymorphic types already have one. That is an implementation bundle, not proof that type identity requires virtual functions in principle — [`std::variant`](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) stores an explicit **index** tag without any virtual function; [`std::any`](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) stores a **manager pointer** tag without inheritance. C++ simply chose to attach `type_info` to polymorphic class metadata rather than to every object.

### What runtime reads

- **`typeid(*p)`** — for polymorphic `p`, returns the **dynamic** type's `type_info`.
- **`dynamic_cast<T>(p)`** — compares the object's dynamic `type_info` against `T`'s place in the inheritance graph. On success returns an adjusted pointer or reference; on failure returns `nullptr` (pointer form) or throws `std::bad_cast` (reference form).

This is C++'s built-in **introspection** for polymorphic types ([Type Systems: introspection](https://shan-weiqiang.github.io/2024/07/14/understanding-types.html)). It is **not** reflection (no arbitrary "get field by name"), not open-ended dynamic typing (contrast Python or `nlohmann::json`), and unavailable when the translation unit is built with `-fno-rtti`. It still does not violate static typing: `typeid` returns metadata for types that were **compiled in**, not types invented at runtime.

## Type erasure, virtual dispatch, and recovery — same static rule

All three patterns defer **which branch runs**; none defer **knowing the types**:

| Pattern | Call site names | Compile time generates | Runtime selects |
| --- | --- | --- | --- |
| Virtual dispatch | `Base&` only | vtable slots for each override | which override |
| Type erasure (Part I, Part V) | erased interface only | per-type implementations | which function pointer / index |
| `dynamic_cast` | **`Derived`** explicitly | `type_info`, cast paths | whether object **is** that `Derived` |

Virtual dispatch and inheritance **abstract the call site** away from derived types — that is the design purpose of `Base*`. `dynamic_cast` **reverses that at one line of code** by naming `Derived` again. That feels like a contradiction until you see both as **selection among compile-time-known types**, with different rules for what the caller may spell in source.

Type is erased from the **caller's interface**, not from the **object** and not from the **compiler's model**. A `Shape&` hides `Circle` from the caller, but `Circle` is still in the binary, and a polymorphic `Circle` still carries vtable metadata including `type_info`.

| | Virtual / type erasure | RTTI / `dynamic_cast` |
| --- | --- | --- |
| Caller names concrete type at compile time? | No | **Yes** (in `dynamic_cast<T>`) |
| Callable surface after dispatch | Base interface only | **Full derived API** |
| Signatures across branches | Uniform | **May differ** |
| Typical goal | Generic algorithm over many types | **Verify and recover** one named type at a boundary |

RTTI lets a specific call site **opt back in** to a compile-time-named type after a runtime check. You never opt in to a type the compiler did not already know — that is why it should stay a **boundary** tool, not the default design.

## What RTTI / dynamic_cast is for

### 1. Safe downcast

- **Problem:** Code holds `Base*` but this path needs `Derived*` (extra members, non-virtual helpers).
- **Mechanism:** `dynamic_cast<Derived*>(p)` compares runtime `type_info`.
- **Benefit:** Avoid undefined behavior of `static_cast` when the dynamic type might not be `Derived`.

### 2. Typed recovery from erased storage

- **Problem:** A container erases type (`shared_ptr` control block, custom deleter) but the caller needs the original typed resource.
- **Mechanism:** Store the concrete type in the implementation; expose a `typeid` query at runtime.


### 3. Operations outside the virtual interface

- **Problem:** The base class cannot list every future operation (fat visitor, cross-cutting concerns).
- **Mechanism:** First dispatch via virtual `accept`; second via `dynamic_cast<SpecificVisitor*>` then non-virtual `visitCircle`.
- **Benefit:** Add operations without growing the base vtable — at the cost of coupling visited code to **named** visitor subtypes.

See [Double Dispatch and the Visitor Pattern — Step 7](https://shan-weiqiang.github.io/2026/07/04/cpp-double-dispatch-visitor-pattern.html#step-7--fine-grained-visitors-one-operation-per-derived-class) for the fine-grained visitor variant.

### 4. Localized escape hatch

- **Problem:** Most code is generic on `Base&`, but one hot path needs concrete type.
- **Mechanism:** Generic path uses the base interface; the exception path uses `dynamic_cast`.
- **Benefit:** Breach abstraction only where justified, without redesigning the hierarchy.

### What it is not

RTTI does **not** let callers avoid knowing `T` at compile time — you must write `dynamic_cast<T>`. It does **not** add types at runtime that were absent from the build. It does **not** replace virtual dispatch or type erasure for open-ended generic algorithms (Parts I–V). Overuse breaks the open/closed principle — same cost as chaining `dynamic_cast` in visitor code.

## Examples

### Shape / Circle — non-virtual API after recovery

```cpp
struct Shape {
  virtual ~Shape() = default;
  virtual void draw() const = 0;
};

struct Circle : Shape {
  void draw() const override { /* ... */ }
  double radius() const { return r_; }
  double r_;
};

void maybe_optimize(const Shape& s) {
  if (auto* c = dynamic_cast<const Circle*>(&s)) {
    use_fast_circle_path(c->radius());  // non-virtual, derived-only
  } else {
    s.draw();
  }
}
```

Most callers call `draw()` and never name `Circle` in source — the static type at the call site is `Shape`. `maybe_optimize` **does** name `Circle`, because `radius()` is not on `Shape`; RTTI verifies the object matches that compile-time-named type before calling it.


## Summary

C++ is **statically typed**: runtime dispatch — virtual, type-erased, or RTTI — always **selects among types the compiler already knew**. It never introduces a usable type that was absent from the build.

Parts I–V **hide type at the call site** and dispatch **behavior** through uniform interfaces (vtable on open hierarchies; index + table on `variant`). Part VI adds: on polymorphic objects, **type identity survives as metadata**, and RTTI lets you **name** a derived type in source and **verify** it at runtime before using derived-only APIs.

**Rule of thumb:** use virtual dispatch and type erasure when call sites should not name concrete types; use `dynamic_cast` sparingly when a specific call site **must** name and verify `T` — understanding that `T` was always a compile-time commitment.

Full series synthesis: [Type Erasure: Part VIII — Final Thoughts](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-eight-final-thoughts.html).

---
layout: post
title:  "Type Erasure: Part VIII — Final Thoughts"
date:   2026-07-05 14:00:00 +0800
tags: [data-typing]
---

Previously:

- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure Part Two: How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure Part Three: Downsides and Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure Part Four: ROS 2 Message Type System](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)
- [Type Erasure: Part V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
- [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure: Part VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)

Parts I–VII walked through mechanisms — virtual dispatch, `std::function`, ROS 2 handles, `std::variant`, RTTI, and `std::any`. This closing part states what they share: **one type-erasure core**, **unchanged static typing**, **generalization as the real payoff**, and **type recovery** as the deliberate reverse when you must name a concrete type again.

* toc
{:toc}

## 1. The core implementation logic — one mechanism

[Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) named the pattern. Every facility in this series is a variation on the same implementation logic:

1. **Same interface, specific type in implementation** — the call site sees one uniform type; concrete logic lives elsewhere.
2. **Binding** — **compile time generates** each type's handler and **hardcodes** it in the binary; **construction records** which handler this object carries (`_M_manager`, vptr, active `index()`). Binding does **not** invoke the handler.
3. **Runtime dispatch** — a call through the uniform interface **selects and jumps to** the handler via **function pointers of the same signature**.

```text
Interface (uniform)  →  Tag (runtime)  →  Table / fn-ptr (same signature)  →  Concrete T handler
```

### Binding vs dispatch — three phases

| Phase | What happens | Examples |
| --- | --- | --- |
| **Compile time (binding)** | Compiler/codegen **generates** per-type handlers and **fixes them in the binary** | vtables, `_Function_handler<F>`, `_Manager<T>::_S_manage`, variant visit thunks, ROS 2 typesupport entry per `.msg` |
| **Construction (binding)** | This object **records** which handler is active | `Shape*` points at a `Circle`; `std::function` stores a lambda; `any = 42` sets `_M_manager` for `int` |
| **Runtime (dispatch)** | A call **selects and invokes** the handler already in the binary | vtable slot jump, `_M_invoker`, `visit` by `index()`, `handle->func` |

After construction, the **interface** no longer names the active type. **Dispatch** at runtime **selects among handlers already hardcoded** — it does not generate new handlers or new types.

### One table, five encodings

| Facility | Interface at call site | Runtime tag | Redirect | Candidates |
| --- | --- | --- | --- | --- |
| Virtual inheritance | `Base&` | vptr + slot | vtable | **Open** — [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) |
| `std::function` | `R(Args…)` | `_M_manager` + `_M_invoker` | manager + invoke | **Open** callables — [Part II](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html) |
| `std::any` | `std::any` | `_M_manager` | opcode `_S_manage` | **Open** stored types — [Part VII](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) |
| `std::variant` | `variant<Ts…>` | `index()` | visit / lifetime table | **Closed** — fixed set — [Part V](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) |
| ROS 2 messages | `const rosidl_message_type_support_t *` | handle + `typesupport_identifier` | `handle->func` resolver | **Open** — one generated entry per message — [Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) |

**`std::function`, virtual hierarchies, `std::any`, and ROS 2 share the same mechanism underneath** — uniform interface, runtime tag, redirect through same-signature function pointers, handlers **generated at compile time**, active handler **recorded at construction** (or fixed per message at codegen). **`std::variant` uses the same tag+table core**; the only structural difference is that **dispatch candidates are fixed** in `variant<Ts…>` at compile time instead of growing through open inheritance or per-site construction.

![Virtual vs variant: binding at construction sets runtime tag, redirect table selects handler](/assets/images/type_erasure_virtual_variant_dispatch.png)

![std::any: manager pointer bound at construction, opcode dispatch for lifetime](/assets/images/type_erasure_any_dispatch.png)

### ROS 2 — same signature, per-message generated entry

[Part IV — ROS 2](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) is the same pattern at ecosystem scale. Middleware and `rcl`/`rclcpp` hold **`const rosidl_message_type_support_t *`** — one handle type — not `demo_pkg::msg::DemoStatus` at every call site. Each message type gets its **own** `extern "C"` entry function at **codegen** time; every entry shares the **same signature**:

```cpp
// Generated once per message type — same return type and signature for all messages
extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_c, demo_pkg, msg, DemoStatus)()
{
  return &::demo_pkg::msg::rosidl_typesupport_c::DemoStatus_message_type_support_handle;
}
```

For `DemoCommand`, code generation emits a **different** function (`…__DemoCommand`) that returns **that** message's handle — parallel to `less` vs `more` in Part I's `qsort`, or `_Manager<int>::_S_manage` vs `_Manager<string>::_S_manage` in Part VII. The macro expands to a unique symbol per `(package, msg, Type)`; the **function pointer type** is always `const rosidl_message_type_support_t *(*)()`.

Handlers are **generated and hardcoded at build time**: `rosidl_generate_interfaces` emits the handle struct, dispatch map, and entry symbol for each `.msg` file. **Dispatch** happens at runtime when generic code calls `handle->func(handle, "rosidl_typesupport_fastrtps_c")` — **same-signature** redirect through the resolver — to reach FastDDS serialize callbacks for **that** message. No middleware layer branches on “if DemoStatus … else if DemoCommand …”; each type's logic lives in generated code wired through the uniform handle.

```text
rcl publish path          const rosidl_message_type_support_t *     Per-message generated code
void* + handle            handle->func (same signature)             DemoStatus vs DemoCommand entries
```

> **Dispatch is redirection of function pointers, with the same signature.** — [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)

That sentence covers virtual slots, `std::function`'s `_M_invoker`, `any`'s `_S_manage` opcodes, variant's `__do_visit` thunks, and ROS 2's `rosidl_message_typesupport_handle_function`. Different surface encoding; **same core**.

---

## 2. Compile time and runtime — C++ stays statically typed

Type erasure, `std::variant`, RTTI, and `dynamic_cast` **do not** turn C++ into a dynamically typed language. They change **what call sites may name** and **which precompiled handler runs** — not **which types exist in the program**.

| Misread | Correct |
| --- | --- |
| “Runtime polymorphism = types appear at runtime” | Types are fixed at compile time; **which handler runs** varies at runtime |
| “RTTI discovers new types” | RTTI **checks** `type_info` for types **named in source** — [Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) |
| “`any` holds unknown types” | `any` holds one of many **compile-time-known** `T`; construction **records** which handler is active |

**Every type** in play — base classes, derived classes, lambda closure types, each member of `variant<int, string, …>`, every `T` ever stored in an `any`, every ROS 2 `.msg` type with its generated typesupport symbol — must be **known when you compile** and have handler code **hardcoded in the binary** before the program runs. Runtime **never introduces** a usable type the compiler did not already generate.

What actually splits compile time, construction, and runtime:

- **Compile time (binding)** — **generate** all handlers; each type's logic is **fixed in the object file** (`Circle::draw`, `_Manager<string>::_S_manage`, visit thunks for each alternative).
- **Construction (binding)** — this object **records** which handler is active (`_M_manager`, vptr, active `index()`).
- **Runtime (dispatch)** — a call **selects and invokes** the handler via same-signature function pointers. Handler **selection** is dispatch; no new types, no new handler generation.

[Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) stated this rule for RTTI; it applies equally to every part of the series:

> **C++ is statically typed.** If your program can *use* a type, that type must be **known at compile time**. **Dispatch** at runtime **selects among** handlers already hardcoded in the binary.

---

## 3. What type erasure brings to programming — generalization, not “runtime types”

The essence of type erasure is **not** “runtime typing.” It is **generalization**: write **common logic once** over a **uniform interface**, without that common code depending on which concrete types will use it later.

### The variation point

[Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) used `qsort` + `bool (*)(const void*, const void*)`:

- **`qsort`** implements sorting **once** — common behavior over an erased compare interface.
- **`less` / `more`** supply per-type compare logic at the edge.
- Without the erased interface, you duplicate the sort algorithm for every element type.

The same shape appears everywhere in this series:

| Common logic (sunk down) | Erased interface | Per-type detail at the edge |
| --- | --- | --- |
| Sorting | compare fn-ptr | `less`, `more` for each struct |
| Draw pipeline | `Shape&` + virtual `draw()` | `Circle::draw`, `Rectangle::draw` |
| Callback registration | `std::function<void()>` | each lambda or function object passed in |
| Heterogeneous bag | `std::any` / `vector<any>` | each `any = T` construction site |
| Closed dispatch | `std::visit(f, v)` | each handler branch for `Ti` |
| ROS 2 publish / serialize | `rosidl_message_type_support_t` + `void*` | per-message `ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(…)` entry — [Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) |

**Maintainability** improves because shared algorithms live in one place. **Reuse** improves because new types plug in through the binding edge (new derived class, new compare function, new `any` assignment) instead of forking the common code.

### Common behavior, not concrete types

Type erasure abstracts **behavior shared by many types** — comparing, drawing, invoking, storing, serializing — and pushes **type-specific facts** to constructors, overrides, and cast sites. The middle layer speaks only the uniform interface.

That is the engineering payoff: **decouple general algorithms from the types that will eventually use them**, while staying in a **statically typed** language.

### Where RTTI fits (without conflating it with erasure)

[RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) is **not** type erasure. It attaches **type identity metadata** to polymorphic objects so code can **verify** “is this actually a `Circle`?” — still for types **named in source** at compile time. It supports **checks and tooling**, not the “hide type at call site / dispatch behavior through one interface” goal of Parts I–V, VII, and ROS 2 in IV.

Use the split deliberately:

- **Type erasure (Parts I–V, VII, ROS 2 in IV)** — call sites **must not** name every concrete type; behavior dispatches through a uniform interface.
- **RTTI (Part VI)** — when identity metadata is needed for **verification** on open hierarchies.

> All types — base, derived, and stored alternatives — are known at compile time. **Compile time generates** each handler and **hardcodes** it in the binary; construction **records** which handler an object carries. **Runtime dispatch selects and invokes** among those handlers through function pointers of the **same signature**.

---

## 4. Type recovery — the reverse direction

Type erasure **removes** concrete type names from call sites. **`dynamic_cast`** and **`any_cast`** **re-introduce** them — on purpose, at specific boundaries.

| Direction | Mechanism | Call site names `T`? |
| --- | --- | --- |
| **Type erasure** | uniform interface + fn-ptr dispatch | **No** — `Base&`, `std::any`, `variant` at use site |
| **Type recovery** | `dynamic_cast<T>`, `any_cast<T>` | **Yes** — you write `T` in the cast |

- **`dynamic_cast<Derived*>`** ([Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)) — recover `Derived*` from `Base*` when you need a derived-only API (`radius()` on `Circle`, not on `Shape`).
- **`any_cast<T>`** ([Part VII](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)) — recover stored `T` from `any`; compare types with `type()` first, then cast. Value comparison also requires naming `T` — see [Comparing two `std::any` objects](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html#comparing-two-stdany-objects).

Recovery is the **reverse** of erasure: you trade the uniform interface for concrete type knowledge at **this** line of code.

### Use recovery sparingly

Every `dynamic_cast` or `any_cast` ties a call site to a **specific** type again. That **offsets** the maintainability benefit of erasure if it spreads through the codebase. The pattern that works:

- **Erasure** for general algorithms, plugin boundaries, and shared containers — logic that should not know future user types.
- **Recovery** as a **localized escape hatch** — optimization, derived-only APIs, serialization adapters, assertions at a boundary.

Most code should call `draw()` on `Shape&` or hold `std::any` in a generic pipeline; only the few lines that truly need `Circle` should say `Circle`.

---

## Summary

- **One mechanism** — same interface, type-specific implementation, handlers **generated at compile time**, active handler **recorded at construction**, **runtime dispatch** via same-signature function pointers. Virtual, `std::function`, `std::any`, `std::variant` (closed candidates), and ROS 2 `rosidl_message_type_support_t` all fit.
- **Static typing unchanged** — every type is compile-time-known; **dispatch** at runtime **selects among** handlers already in the binary.
- **Real benefit: generalization** — sink common behavior; per-type details at the edges; not “runtime types.”
- **Recovery is the complement** — `dynamic_cast` / `any_cast` re-expose concrete types; use sparingly so erasure keeps its leverage.

---

## Series index

| Part | Topic |
| --- | --- |
| [I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) | Interface, binding, dispatch; `qsort`; virtual erasure |
| [II — std::function](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html) | Callable erasure; `_M_manager` + `_M_invoker` |
| [III — Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html) | Costs and when not to erase |
| [IV — ROS 2](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) | Erased handles in a message system |
| [V — std::variant](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) | Closed-set value erasure; `index()` + table |
| [VI — RTTI / dynamic_cast](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) | Type identity; static typing rule |
| [VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) | Open-set value erasure; manager pointer tag |
| **VIII — Final Thoughts** (this post) | Synthesis: one mechanism, generalization, recovery |

---

## References

- [Type Erasure: Part I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure: Part VI — dynamic_cast and RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure: Part VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)
- [C++ Type Erasure Demystified — Fedor G Pikus (C++Now 2024)](https://www.youtube.com/watch?v=p-qaf6OS_f4)

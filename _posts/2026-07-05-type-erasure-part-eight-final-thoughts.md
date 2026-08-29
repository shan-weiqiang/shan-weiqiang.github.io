---
layout: post
title:  "Type Erasure VIII — Final Thoughts"
date:   2026-07-05 14:00:00 +0800
tags: [cpp, type-erasure, polymorphism, type-systems]
---

Previously:

- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure II — std::function](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure III — Trade-offs](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)
- [Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html)
- [V — Closed Tagged Dispatch](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html)
- [Type Erasure VI — dynamic_cast & RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)

> **Editor's note:** This synthesis was revised to separate `std::variant`'s
> closed tagged dispatch from type-erased interfaces.

Parts I–VII walked through virtual dispatch, `std::function`, ROS 2 handles,
`std::variant`, RTTI, and `std::any`. This closing part separates the mechanisms
that perform type erasure from related runtime-polymorphism techniques. They all
preserve C++ static typing, but they do not all erase types.

* toc
{:toc}

## 1. The core implementation logic

[Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) named the pattern. The type-erased facilities in this series share this implementation logic:

1. **Same interface, specific type in implementation** — the call site sees one uniform type; concrete logic lives elsewhere.
2. **Binding** — **compile time generates** each type's handler and **hardcodes** it in the binary; **construction records** which handler an erased object carries (`_M_manager`, vptr). Binding does **not** invoke the handler.
3. **Runtime dispatch** — a call through the uniform interface **selects and jumps to** the handler via **function pointers of the same signature**.

```text
Interface (uniform)  →  Tag (runtime)  →  Table / fn-ptr (same signature)  →  Concrete T handler
```

### Binding vs dispatch — three phases

| Phase | What happens | Examples |
| --- | --- | --- |
| **Compile time (generation)** | Compiler/codegen **generates** per-type handlers and **fixes them in the binary** | vtables, `_Function_handler<F>`, `_Manager<T>::_S_manage`, ROS 2 typesupport entry per `.msg` |
| **Construction (binding)** | This object **records** which erased handler is active | a `Circle` object receives its vptr; `std::function` stores a lambda; `any = 42` sets `_M_manager` for `int` |
| **Runtime (dispatch)** | A call **selects and invokes** the handler already in the binary | vtable slot jump, `_M_invoker`, `_M_manager`, `handle->func` |

After construction, the **interface** no longer names the active type. **Dispatch** at runtime **selects among handlers already hardcoded** — it does not generate new handlers or new types.

### Type-erased interfaces and their redirects

| Facility | Interface at call site | Runtime tag | Redirect | Candidates |
| --- | --- | --- | --- | --- |
| Virtual inheritance | `Base&` | vptr + slot | vtable | **Open** — [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) |
| `std::function` | `R(Args…)` | `_M_manager` + `_M_invoker` | manager + invoke | **Open** callables — [Part II](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html) |
| `std::any` | `std::any` | `_M_manager` | opcode `_S_manage` | **Open** stored types — [Part VII](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) |
| ROS 2 messages | `const rosidl_message_type_support_t *` | handle + `typesupport_identifier` | `handle->func` resolver | **Open** — one generated entry per message — [Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) |

**`std::function`, virtual hierarchies, `std::any`, and ROS 2 share the same
operational type-erasure pattern** — a uniform interface omits concrete
implementation types while runtime state redirects to type-specific code.

`std::variant` is the important counterexample. It also has runtime state and
generated dispatch code, but `variant<Ts...>` exposes the complete alternative
set. It is a closed tagged union and runtime polymorphism without type erasure.

![Virtual type erasure compared with std::variant closed tagged dispatch](/assets/images/type_erasure_virtual_variant_dispatch.png)

![std::any: manager pointer bound at construction, opcode dispatch for lifetime](/assets/images/type_erasure_any_dispatch.png)

### ROS 2 — same signature, per-message generated entry

[Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) is the same pattern at ecosystem scale. Middleware and `rcl`/`rclcpp` hold **`const rosidl_message_type_support_t *`** — one handle type — not `demo_pkg::msg::DemoStatus` at every call site. Each message type gets its **own** `extern "C"` entry function at **codegen** time; every entry shares the **same signature**:

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

That sentence covers virtual slots, `std::function`'s `_M_invoker`, `any`'s
`_S_manage` opcodes, and ROS 2's
`rosidl_message_typesupport_handle_function`. `std::variant` may also use
function tables, but its public type still enumerates every alternative; the
shared dispatch instruction does not make it erased.

---

## 2. Compile time and runtime — C++ stays statically typed

Type erasure, `std::variant`, RTTI, and `dynamic_cast` **do not** turn C++ into
a dynamically typed language. Type erasure changes what a consumer interface
must name; `variant` exposes a closed list but changes which member is active;
RTTI verifies a compile-time-named type. None changes which C++ types exist in
the program.

| Misread | Correct |
| --- | --- |
| “Runtime polymorphism = types appear at runtime” | Types are fixed at compile time; **which handler runs** varies at runtime |
| “RTTI discovers new types” | RTTI **checks** `type_info` for types **named in source** — [Part VI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) |
| “`any` holds unknown types” | `any` holds one of many **compile-time-known** `T`; construction **records** which handler is active |

**Every type** in play — base classes, derived classes, lambda closure types, each member of `variant<int, string, …>`, every `T` ever stored in an `any`, every ROS 2 `.msg` type with its generated typesupport symbol — must be **known when you compile** and have handler code **hardcoded in the binary** before the program runs. Runtime **never introduces** a usable type the compiler did not already generate.

What actually splits compile time, construction, and runtime:

- **Compile time (generation)** — generate all handlers; each type's logic is
  fixed in the object file (`Circle::draw`, `_Manager<string>::_S_manage`, and
  visitor branches for every variant alternative).
- **Construction (runtime state)** — an erased object records its matching
  operation state (`_M_manager`, vptr); a variant records its active `index()`.
- **Runtime (dispatch)** — a call follows the abstraction's dispatch protocol
  to an already-generated handler. No new type or handler is generated.

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
| Closed tagged dispatch | `std::visit(f, v)` | each compile-time-enumerated handler branch for `Ti` |
| ROS 2 publish / serialize | `rosidl_message_type_support_t` + `void*` | per-message `ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(…)` entry — [Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) |

Type erasure improves maintainability because shared algorithms live in one
place and new implementation types plug in at the binding edge. Closed tagged
dispatch also centralizes behavior, but adding a new variant alternative changes
the public union type and requires recompiling exhaustive visitors.

### Common behavior, not concrete types

Type erasure abstracts **behavior shared by many types** — comparing, drawing, invoking, storing, serializing — and pushes **type-specific facts** to constructors, overrides, and cast sites. The middle layer speaks only the uniform interface.

That is the engineering payoff: **decouple general algorithms from the types that will eventually use them**, while staying in a **statically typed** language.

### Where RTTI fits (without conflating it with erasure)

[RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) is **not** type erasure. It attaches **type identity metadata** to polymorphic objects so code can **verify** “is this actually a `Circle`?” — still for types **named in source** at compile time. It supports **checks and tooling**, not the “hide type at call site / dispatch behavior through one interface” goal of Parts I–IV, VII, and ROS 2 in IV.

Use the split deliberately:

- **Type erasure (Parts I–IV, VII, ROS 2 in IV)** — call sites **must not** name every concrete type; behavior dispatches through a uniform interface.
- **Closed tagged dispatch (Part V)** — the public union type names every
  alternative and runtime selects the active one.
- **RTTI (Part VI)** — when identity metadata is needed for **verification** on open hierarchies.

> All types — base, derived, and stored alternatives — are known at compile
> time. Compile time generates each handler and hardcodes it in the binary;
> runtime state selects among those handlers through the mechanism defined by
> the abstraction.

---

## 4. Type recovery — the reverse direction

Type erasure **removes** concrete type names from call sites. **`dynamic_cast`** and **`any_cast`** **re-introduce** them — on purpose, at specific boundaries.

| Direction | Mechanism | Call site names `T`? |
| --- | --- | --- |
| **Type erasure** | uniform interface + fn-ptr dispatch | **No** — `Base&`, `std::any` at use site |
| **Closed tagged dispatch** | `variant<Ts...>` + active index | **Yes, in the public alternative list** |
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

- **Type erasure** — virtual interfaces, `std::function`, `std::any`, and ROS 2
  handles hide concrete implementation types behind uniform contracts and
  runtime redirects.
- **Closed tagged dispatch is different** — `std::variant` performs runtime
  selection while explicitly enumerating every alternative in its public type.
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
| [V — Closed Tagged Dispatch](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-five-variant.html) | `std::variant`; closed union; `index()` + dispatch |
| [VI — RTTI / dynamic_cast](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html) | Type identity; static typing rule |
| [VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html) | Open-set value erasure; manager pointer tag |
| **VIII — Final Thoughts** (this post) | Synthesis: one mechanism, generalization, recovery |

---

## References

- [Type Erasure I — Core Logic](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure VI — dynamic_cast & RTTI](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-six-dynamic-cast-rtti.html)
- [Type Erasure VII — std::any](https://shan-weiqiang.github.io/2026/07/05/type-erasure-part-seven-any.html)
- [C++ Type Erasure Demystified — Fedor G Pikus (C++Now 2024)](https://www.youtube.com/watch?v=p-qaf6OS_f4)

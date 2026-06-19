---
layout: post
title:  "Type Erasure Part Four: ROS 2 Message Type System"
date:   2026-06-13 10:00:00 +0800
tags: [data-typing]
---

Previously:

- [Type Erasure: Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure Part Two: How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure Part Three: The Downside](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html)


Now:


* toc
{:toc}


## Introduction

In [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) I described type erasure as hiding concrete type information behind a uniform interface, with runtime dispatch redirecting through function pointers of the same signature. ROS 2 message generation is one of the largest real-world deployments of that pattern across three languages.

Start with a single `.msg` file:

```
# demo_pkg/msg/DemoStatus.msg
std_msgs/Header header
string name
int32 code
bool active
```

Run `colcon build` on a package that declares it via `rosidl_generate_interfaces()`, and the build tree grows into language bindings, serialization code, introspection metadata, dispatchers, and shared libraries. At runtime the middleware does not operate on `demo_pkg::msg::DemoStatus` directly in most layers. It operates on **`void*` message pointers**, **string identifiers**, and **`rosidl_message_type_support_t` handles** — the ROS equivalent of `qsort`'s type-erased compare function.

This article walks through the generated code for `DemoStatus` from a local `demo_pkg` workspace (ROS 2 Jazzy, C/C++/Python only; Rust bindings are disabled in that package and are not covered here). The goal is to map **folder layout**, **shared library roles**, and **where type erasure happens at compile time** versus **where dispatch happens at runtime**.

| Type erasure concept (Parts I–III) | ROS 2 analogue |
| --- | --- |
| Type-erased interface | `rosidl_message_type_support_t` |
| Common algorithm over erased types | RMW publish/subscribe, `ros2 topic echo`, Python bindings |
| Per-type implementation | Per-message generated structs/classes + callback tables |
| Runtime dispatch | `func` resolver + `dlopen`/`dlsym` in dispatcher |
| Manual create/copy when type is erased | C `DemoStatus__create` / introspection init-fini |
| Binding fixed at compile time | Template specialization + macro-expanded `extern "C"` symbols |

---

## Build pipeline: from `.msg` to generated tree

`colcon build` invokes CMake, which calls `rosidl_generate_interfaces()`. That macro drives every generator registered in the ROS installation.

```text
DemoStatus.msg
  → rosidl_adapter → DemoStatus.idl
  → rosidl_generate_interfaces
       ├→ rosidl_generator_c / _cpp / _py
       ├→ rosidl_typesupport_fastrtps_* / introspection_*
       └→ rosidl_typesupport_c / _cpp
```

Each generator writes into its own subfolder under `build/demo_pkg/`. `colcon` then links the outputs into package-level shared libraries under `install/demo_pkg/lib/`. The mapping from **build folders**, **`.so` files**, and **what each layer does** is summarized in [Package libraries vs message symbols](#package-libraries-vs-message-symbols) below.

### Package libraries vs message symbols

Do not confuse **shared libraries** (one per package per layer) with **exported symbols** (many per message inside each library).

ROS 2 groups generated code by **package** and **layer**, not by individual message:

```
one package  ×  one layer variant  →  one .so file
one .so file  ×  many messages in that package  →  many extern "C" symbols
```

Naming convention (from `ROSIDL_TYPESUPPORT_INTERFACE__LIBRARY_NAME`):

```text
lib<package_name>__<typesupport_layer>.so
```

#### Four layers

Typesupport for a message package splits into **four layers**. ROS builds **C and C++ track variants** of the dispatcher and implementation layers (`*_c` / `*_cpp` suffixes); the role of each layer is the same — language bindings are consumers, not separate layers.

| Layer | Build folders (pattern) | Shared libraries (pattern) | Role | Key artifact per message (`DemoStatus`) |
| --- | --- | --- | --- | --- |
| **Definition** | `rosidl_generator_c/`, `_cpp/`, `_py/` | `lib<pkg>__rosidl_generator_c.so`, `_py.so` (+ C++ headers) | Concrete message layout and lifecycle (`__create` / `__destroy`); when middleware holds `void*`, those are the manual ops from [Part III](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html). Forward-declares dispatcher symbols in headers only — no FastDDS or introspection logic. | `demo_status__struct.h`, `DemoStatus__create` / `__destroy` |
| **FastDDS** | `rosidl_typesupport_fastrtps_c/`, `_cpp/` | `lib<pkg>__rosidl_typesupport_fastrtps_c.so`, `_cpp.so` | Wire serialization: `message_type_support_callbacks_t` with `cdr_serialize` / `cdr_deserialize` on `void*`. Generated code casts internally to `demo_pkg__msg__DemoStatus *`; the callback table erases the type at the interface. | `demo_status__type_support_c.cpp`, `__callbacks_DemoStatus` |
| **Introspection** | `rosidl_typesupport_introspection_c/`, `_cpp/` | `lib<pkg>__rosidl_typesupport_introspection_c.so`, `_cpp.so` | Static field names, types, and `offsetof` for tools such as `ros2 topic echo`. Unlike [Protobuf reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html), metadata is compiled from `.msg` files, not parsed at runtime. | `demo_status__type_support.c`, `MessageMembers` |
| **Dispatcher** | `rosidl_typesupport_c/`, `_cpp/` | `lib<pkg>__rosidl_typesupport_c.so`, `_cpp.so` | Front door: no serialization. Each message handle holds a `type_support_map_t` — implementation identifiers, macro-stringified `dlsym` names, cached `dlopen` handles — and a `func` that resolves FastDDS or introspection on first use. | `demo_status__type_support.cpp`, dispatch map |

For `demo_pkg` (`DemoStatus` + `DemoCommand`), the install tree has **eight** shared libraries — two per layer (C/C++ tracks for dispatcher, FastDDS, and introspection; definition adds `rosidl_generator_c` and `rosidl_generator_py`, with C++ as headers). Separate `build/` sources exist per message but link into the same `.so` per layer.

#### Symbols inside each `.so`

Dispatcher, FastDDS, and introspection each export one `extern "C"` entry symbol per message inside their package library. The C track (`*_c` suffix) illustrates the pattern; the C++ track uses the same layout with `*_cpp` identifiers.

**Dispatcher layer** — `libdemo_pkg__rosidl_typesupport_c.so`:

```text
rosidl_typesupport_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus
rosidl_typesupport_c__get_message_type_support_handle__demo_pkg__msg__DemoCommand
```

**FastDDS layer** — `libdemo_pkg__rosidl_typesupport_fastrtps_c.so`:

```text
rosidl_typesupport_fastrtps_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus
rosidl_typesupport_fastrtps_c__get_message_type_support_handle__demo_pkg__msg__DemoCommand
```

**Introspection layer** — `libdemo_pkg__rosidl_typesupport_introspection_c.so` (resolved when the dispatcher map matches `"rosidl_typesupport_introspection_c"`):

```text
rosidl_typesupport_introspection_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus
rosidl_typesupport_introspection_c__get_message_type_support_handle__demo_pkg__msg__DemoCommand
```

The **definition layer** exposes lifecycle helpers such as `demo_pkg__msg__DemoStatus__create`; the **FastDDS layer** exposes `cdr_serialize_demo_pkg__msg__DemoStatus`. Only dispatcher, FastDDS, and introspection use the `get_message_type_support_handle` entry pattern shown above.

| Granularity | What you get | Count for `demo_pkg` (2 msgs) |
| --- | --- | --- |
| Layer variant library | One `.so` per package per layer variant | 8 shared libraries (4 layers × C/C++ tracks, plus definition generators) |
| Message symbol | One `extern "C"` entry per message per typesupport layer | 2 symbols per dispatcher / FastDDS / introspection library |
| Static data per message | Dispatch map, callbacks, struct layout | Separate sources in `build/`, merged at link time |

When the dispatcher's `func` runs, it `dlopen`s a **package-level** implementation library (`libdemo_pkg__rosidl_typesupport_fastrtps_c.so`), then `dlsym`s a **message-specific** symbol string from that message's dispatch map. Adding a new `.msg` file adds symbols to existing `.so` files; it does not create new libraries per message.

All message code is **statically generated** before the node runs. ROS "dynamic typing" means introspection plus runtime library loading for **known** types — not arbitrary schemas at runtime (see [`rosidl_dynamic_typesupport`](https://github.com/ros2/rosidl_dynamic_typesupport) for that direction).

---

## The core erased handle: `rosidl_message_type_support_t`

The **definition layer** does not use this struct — it exposes concrete message layouts and `__create` / `__destroy` directly. **Dispatcher, FastDDS, and introspection** each publish a `const rosidl_message_type_support_t *`: one polymorphic handle type that lets generic middleware code work with any message without knowing its C++ class or struct layout at the call site.

```cpp
// rosidl_runtime_c/message_type_support_struct.h
typedef const rosidl_message_type_support_t * (* rosidl_message_typesupport_handle_function)(
  const rosidl_message_type_support_t *, const char *);

struct rosidl_message_type_support_t
{
  const char * typesupport_identifier;
  const void * data;
  rosidl_message_typesupport_handle_function func;
  // Jazzy also carries type hash / description hooks; omitted here for clarity
};
```

Three fields, three roles:

- **`typesupport_identifier`** — a string tag saying what kind of handle this is (dispatcher, FastDDS, introspection, …).
- **`data`** — polymorphic payload; the struct type of the pointee depends on `typesupport_identifier`.
- **`func`** — resolver function; given a handle and a requested identifier, returns the handle that actually implements that identifier (often a *different* handle).

### Polymorphic `data`

| `typesupport_identifier` | `data` points to | Purpose |
| --- | --- | --- |
| `rosidl_typesupport_c` / `_cpp` | `type_support_map_t` | Dispatch map: identifiers, `dlsym` symbol names, cached library handles |
| `rosidl_typesupport_fastrtps_c` / `_cpp` | `message_type_support_callbacks_t` | CDR serialize/deserialize on `void*` |
| `rosidl_typesupport_introspection_c` / `_cpp` | `MessageMembers` / introspection tables | Field names, types, offsets |

Callers must inspect the identifier before casting:

```cpp
const rosidl_message_type_support_t * handle = /* ... */;

if (0 == strcmp(handle->typesupport_identifier, "rosidl_typesupport_fastrtps_c")) {
  auto * callbacks = static_cast<const message_type_support_callbacks_t *>(handle->data);
  callbacks->cdr_serialize(untyped_ros_message, cdr);
} else if (0 == strcmp(handle->typesupport_identifier, "rosidl_typesupport_c")) {
  auto * map = static_cast<const type_support_map_t *>(handle->data);
  // map holds symbol names for dlopen/dlsym — not serialization callbacks
}
```

### Polymorphic `func`

When the requested identifier matches the handle's own identifier, `func` returns the same handle. When a **dispatcher** receives a request for `"rosidl_typesupport_fastrtps_c"`, it searches its map, `dlopen`s the implementation library, `dlsym`s the macro-generated `extern "C"` symbol, and returns the **FastDDS handle** — a different struct whose `data` field actually holds serialization callbacks.

A dispatcher handle cannot serialize directly: its `data` is a map, not `message_type_support_callbacks_t`. You must call `func` first — see [How the dispatcher works](#how-the-dispatcher-works) (Steps 0–3).

### How the dispatcher works

The **dispatcher layer** is the same mechanism on both tracks: each message gets a static **dispatch map**, a **dispatcher handle** pointing at that map, and a package **entry symbol** that returns the handle. Nothing in the map serializes messages — it only records which implementation layers exist, the `dlsym` strings to find them, and slots to cache loaded libraries. The shared `func` resolver in `librosidl_typesupport_c.so` / `librosidl_typesupport_cpp.so` does the rest.

The walkthrough below uses `DemoStatus` on the **C track** (`rosidl_typesupport_c`, `fastrtps_c`, `introspection_c`). The C++ track substitutes `_cpp` identifiers and `libdemo_pkg__rosidl_typesupport_cpp.so`; the control flow is identical.

#### Step 0: load the package dispatcher first

Resolving FastDDS or introspection is **Stage 1**. Before that, the process must already contain the **package dispatcher** library — **Stage 0**:

| Stage | Library loaded | Mechanism | Who triggers it |
| --- | --- | --- | --- |
| 0 — package dispatcher | `libdemo_pkg__rosidl_typesupport_c.so` or `_cpp.so` | ELF dynamic linker at process/import time | Node binary, Python extension, or explicit `dlopen` |
| 1 — implementation | `libdemo_pkg__rosidl_typesupport_fastrtps_*.so`, `_introspection_*.so` | `dlopen` inside the runtime `func` resolver | Dispatch map on first use of that implementation |

The dispatch map `dlopen`s only the **FastDDS and introspection** package libraries listed in its rows — for `demo_pkg` on the C track, `libdemo_pkg__rosidl_typesupport_fastrtps_c.so` and `libdemo_pkg__rosidl_typesupport_introspection_c.so` (C++ track: `_fastrtps_cpp.so` and `_introspection_cpp.so`). It does **not** load the dispatcher library (`libdemo_pkg__rosidl_typesupport_c.so` / `_cpp.so`); that must already be mapped through **build-time linkage**, **Python import** of the typesupport extension, or an explicit `dlopen`/`dlsym` of the dispatcher entry symbol.

| Caller | How Stage 0 happens |
| --- | --- |
| **`rclcpp` node** | CMake links `libdemo_pkg__rosidl_typesupport_cpp.so`; `ld.so` loads it at startup; template or macro returns the static dispatcher handle. |
| **`rclpy` / C API** | Import or link pulls in `libdemo_pkg__rosidl_typesupport_c.so`; entry symbol or PyCapsule resolves to the same `extern "C"` function. |
| **Unlinked tool** | Must `dlopen` the dispatcher `.so` and `dlsym` the package entry symbol before calling `func`. |

Confusing Stage 0 with Stage 1 is a common mistake: the first handle comes from **linkage or import**, not from the map's lazy loader.

#### Step 1: generated dispatch map and entry symbol

Each message's dispatcher code is generated into `build/demo_pkg/rosidl_typesupport_<track>/.../demo_status__type_support.cpp`. For `DemoStatus` on the C track:

```cpp
static const _DemoStatus_type_support_ids_t _DemoStatus_message_typesupport_ids = {
  {
    "rosidl_typesupport_fastrtps_c",
    "rosidl_typesupport_introspection_c",
  }
};

static const _DemoStatus_type_support_symbol_names_t _DemoStatus_message_typesupport_symbol_names = {
  {
    STRINGIFY(ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
      rosidl_typesupport_fastrtps_c, demo_pkg, msg, DemoStatus)),
    STRINGIFY(ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
      rosidl_typesupport_introspection_c, demo_pkg, msg, DemoStatus)),
  }
};

static _DemoStatus_type_support_data_t _DemoStatus_message_typesupport_data = {
  { 0, 0 }  // dlopen handles cached here after first use (Stage 1)
};

static const type_support_map_t _DemoStatus_message_typesupport_map = {
  2,
  "demo_pkg",
  &_DemoStatus_message_typesupport_ids.typesupport_identifier[0],
  &_DemoStatus_message_typesupport_symbol_names.symbol_name[0],
  &_DemoStatus_message_typesupport_data.data[0],
};

static const rosidl_message_type_support_t DemoStatus_message_type_support_handle = {
  rosidl_typesupport_c__typesupport_identifier,
  reinterpret_cast<const type_support_map_t *>(&_DemoStatus_message_typesupport_map),
  rosidl_typesupport_c__get_message_typesupport_handle_function,
};
```

A macro-generated **`extern "C"` entry symbol** per message is the stable front door — predictable across compilers, usable from `dlsym`:

```cpp
extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_c, demo_pkg, msg, DemoStatus)()
{
  return &::demo_pkg::msg::rosidl_typesupport_c::DemoStatus_message_type_support_handle;
}

// ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_c, demo_pkg, msg, DemoStatus)
// → rosidl_typesupport_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus
```

Calling the entry symbol does **not** load FastDDS yet. It returns the static dispatcher handle where:

- `typesupport_identifier` names the dispatcher layer (e.g. `"rosidl_typesupport_c"`)
- `data` → the dispatch map (not serialization callbacks)
- `func` → the runtime resolver (`rosidl_typesupport_c__get_message_typesupport_handle_function`)

To publish or serialize, the caller must invoke `handle->func(handle, "<implementation_identifier>")`, for example `"rosidl_typesupport_fastrtps_c"`.

The map rows for `DemoStatus` were fixed at compile time — the resolver never guesses symbol names:

| Map index | `typesupport_identifier[i]` | `symbol_name[i]` (via `STRINGIFY`) |
| --- | --- | --- |
| 0 | `rosidl_typesupport_fastrtps_c` | `rosidl_typesupport_fastrtps_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus` |
| 1 | `rosidl_typesupport_introspection_c` | `rosidl_typesupport_introspection_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus` |

#### Step 2: `func` resolves the requested implementation

The resolver body lives in the ROS 2 runtime library (`rosidl_typesupport_c/src/type_support_dispatch.hpp`). Pseudocode matching the real control flow:

```cpp
const rosidl_message_type_support_t *
rosidl_typesupport_c__get_message_typesupport_handle_function(
  const rosidl_message_type_support_t * handle,
  const char * identifier)
{
  // Case A: caller already holds the implementation handle
  if (0 == strcmp(handle->typesupport_identifier, identifier)) {
    return handle;
  }

  // Case B: caller holds the dispatcher handle
  if (0 == strcmp(handle->typesupport_identifier, "rosidl_typesupport_c")) {
    const type_support_map_t * map = static_cast<const type_support_map_t *>(handle->data);

    for (size_t i = 0; i < map->size; ++i) {
      if (0 != strcmp(map->typesupport_identifier[i], identifier)) {
        continue;
      }

      // Stage 1: lazy-load the implementation shared library once
      if (map->data[i] == nullptr) {
        // library_basename = "<package>__<identifier>"
        // → libdemo_pkg__rosidl_typesupport_fastrtps_c.so on Linux
        map->data[i] = dlopen(...);
      }

      void * sym = dlsym(map->data[i], map->symbol_name[i]);

      auto impl_entry = reinterpret_cast<
        const rosidl_message_type_support_t * (*)()>(sym);

      return impl_entry();  // FastDDS or introspection handle
    }
  }

  return nullptr;
}
```

After the first successful resolution, `map->data[i]` caches the loaded library (`SharedLibrary` wrapping the `dlopen` handle). Later calls skip `dlopen` and repeat only `dlsym` plus the entry call — or reuse a handle cached higher in the middleware.

#### Step 3: implementation entry returns a different handle

The `dlsym` target is **not** `cdr_serialize`. It is a second `extern "C"` entry in the implementation library — for example `libdemo_pkg__rosidl_typesupport_fastrtps_c.so`:

```cpp
extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_fastrtps_c, demo_pkg, msg, DemoStatus)()
{
  return &_DemoStatus__type_support;
}
```

That handle differs from the dispatcher handle:

- `typesupport_identifier == "rosidl_typesupport_fastrtps_c"`
- `data` → `&__callbacks_DemoStatus` (`message_type_support_callbacks_t`)
- `func` → the FastDDS runtime resolver (returns `self` when identifiers match)

Only now can middleware call `callbacks->cdr_serialize(untyped_ros_message, cdr)`.

Two distinct **`extern "C"` entry symbols** appear in every resolution:

1. **Dispatcher entry** (`rosidl_typesupport_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus`) — returns the map-backed handle from the dispatcher `.so`; obtained at Stage 0.
2. **Implementation entry** (`rosidl_typesupport_fastrtps_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus`) — returns the callback-backed handle from the FastDDS `.so`; name stored in the map for Stage 1 `dlsym`.

Both are generated by the same macro family; only the `typesupport_name` token changes (`rosidl_typesupport_c` vs `rosidl_typesupport_fastrtps_c`).

#### End-to-end call chain (first publish)

```text
Caller
  │  Stage 0: link / import / dlsym
  ▼
dispatcher entry symbol ──► dispatcher handle
  │
  │  handle->func(handle, "rosidl_typesupport_fastrtps_c")
  ▼
runtime func resolver (librosidl_typesupport_c.so)
  │  dlopen libdemo_pkg__rosidl_typesupport_fastrtps_c.so (first use)
  │  dlsym symbol from dispatch map
  ▼
fastrtps entry symbol ──► FastDDS handle
  │
  │  callbacks->cdr_serialize via handle->data
  ▼
__callbacks_DemoStatus
```

This is the runtime half of the design from [Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html): compile time generates uniform entry points and callback tables; runtime dispatch selects and loads the right entry point. Dispatch redirects function pointers — it does not erase types.

---

## Dual-track architecture

ROS 2 message type support is split into **two parallel tracks**. Each track has the same three layers — dispatcher, FastDDS serialization, introspection — but different client libraries use different tracks.

```text
C track                          C++ track
────────                         ─────────
rclpy / rcl C API                rclcpp nodes
        │                                │
        ▼                                ▼
rosidl_typesupport_c             rosidl_typesupport_cpp
   │         │                      │         │
   ▼         ▼                      ▼         ▼
fastrtps_c  introspection_c   fastrtps_cpp  introspection_cpp
   │         │                      │         │
   └────┬────┘                      └────┬────┘
        ▼                                ▼
              Fast DDS CDR (wire format)
```

| Client | Track | Why |
| --- | --- | --- |
| **`rclcpp`** (C++ nodes) | C++ track | Typed `Publisher<MsgT>` / `Subscription<MsgT>`; compiler knows message type at compile time |
| **`rclpy`** (Python nodes) | C track | Python cannot call C++ templates; bindings wrap C structs via PyCapsule |
| **`rcl` C API**, generic tools | C track | C has no templates; stable `extern "C"` ABI required |

**Python never uses the C++ track.** `_demo_status_s.c` converts to `demo_pkg__msg__DemoStatus` (a C struct) and loads `demo_pkg_s__rosidl_typesupport_c.so`, which in turn links `libdemo_pkg__rosidl_typesupport_c.so`. The flow is always `rosidl_typesupport_c` → `fastrtps_c` / `introspection_c`.

**C++ nodes never use the C track for their own messages.** `rclcpp` resolves handles through `rosidl_typesupport_cpp` → `fastrtps_cpp` / `introspection_cpp`.

Both tracks converge on the same idea: a **`rosidl_message_type_support_t` handle** from dispatcher, FastDDS, or introspection — obtained through exported symbols, with the dispatcher's `func` loading implementation libraries at runtime. The difference is *how the first handle is reached* and whether C++ adds a second, template-based path.

### How symbols are exported (both tracks)

Regardless of track, **dispatcher, FastDDS, and introspection** each export one stable `extern "C"` function per message. The generator emits these with `ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME`; only the `typesupport_name` token changes:

| Layer | Shared library | Macro `typesupport_name` | Returned handle holds |
| --- | --- | --- | --- |
| C dispatcher | `libdemo_pkg__rosidl_typesupport_c.so` | `rosidl_typesupport_c` | Dispatch map |
| C++ dispatcher | `libdemo_pkg__rosidl_typesupport_cpp.so` | `rosidl_typesupport_cpp` | Dispatch map |
| FastDDS C | `libdemo_pkg__rosidl_typesupport_fastrtps_c.so` | `rosidl_typesupport_fastrtps_c` | CDR callbacks |
| FastDDS C++ | `libdemo_pkg__rosidl_typesupport_fastrtps_cpp.so` | `rosidl_typesupport_fastrtps_cpp` | CDR callbacks |
| Introspection C | `libdemo_pkg__rosidl_typesupport_introspection_c.so` | `rosidl_typesupport_introspection_c` | Field metadata |
| Introspection C++ | `libdemo_pkg__rosidl_typesupport_introspection_cpp.so` | `rosidl_typesupport_introspection_cpp` | Field metadata |

Macro expansion for `DemoStatus` (same pattern, different prefix per row):

```cpp
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_fastrtps_c, demo_pkg, msg, DemoStatus)
// → rosidl_typesupport_fastrtps_c__get_message_type_support_handle__demo_pkg__msg__DemoStatus
```

This is the ROS analogue of Part I's `less(const void*, const void*)`: a uniform function signature (`const rosidl_message_type_support_t *()`), stable across compilers because of `extern "C"`, unique per message and typesupport layer.

**Implementation layer example (FastDDS C)** — the macro returns a handle whose `data` points at serialization callbacks:

```cpp
static message_type_support_callbacks_t __callbacks_DemoStatus = {
  "demo_pkg::msg", "DemoStatus",
  _DemoStatus__cdr_serialize, _DemoStatus__cdr_deserialize,
  _DemoStatus__get_serialized_size, _DemoStatus__max_serialized_size, nullptr
};

static rosidl_message_type_support_t _DemoStatus__type_support = {
  rosidl_typesupport_fastrtps_c__identifier,
  &__callbacks_DemoStatus,
  get_message_typesupport_handle_function,
};

extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_fastrtps_c, demo_pkg, msg, DemoStatus)()
{
  return &_DemoStatus__type_support;
}
```

**C track usage** — macros are the *only* entry mechanism. No templates exist. A Python node or C API caller obtains the dispatcher handle like this:

```c
const rosidl_message_type_support_t * ts =
  ROSIDL_GET_MSG_TYPE_SUPPORT(demo_pkg, msg, DemoStatus);
/* expands to a direct call of the rosidl_typesupport_c macro symbol
   in libdemo_pkg__rosidl_typesupport_c.so */
```

To serialize, the caller invokes `ts->func(ts, "rosidl_typesupport_fastrtps_c")`. The dispatcher `dlsym`s the **FastDDS macro symbol** in `libdemo_pkg__rosidl_typesupport_fastrtps_c.so` ([Step 2](#step-2-func-resolves-the-requested-implementation)). The C track never names C++ templates or mangled symbols.

**C++ track — macro side** — the C++ dispatcher exports the same kind of macro symbol. On the C++ track this macro is still required for `dlsym` when loading `fastrtps_cpp` and `introspection_cpp`:

```cpp
extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_cpp, demo_pkg, msg, DemoStatus)()
{
  return &::demo_pkg::msg::rosidl_typesupport_cpp::DemoStatus_message_type_support_handle;
}
```

The dispatch map in `_DemoStatus_message_typesupport_symbol_names` stores macro symbol **strings** for the implementation layers. Runtime loading always goes through these names — on both tracks.

### C++ additional export: template specializations

The C++ track adds typed access through explicit template specializations. The anchor is a **generic declaration** in the ROS runtime — not generated per message:

```cpp
// rosidl_runtime_cpp/rosidl_typesupport_cpp/message_type_support.hpp
namespace rosidl_typesupport_cpp {

template<typename T>
const rosidl_message_type_support_t * get_message_type_support_handle();

}  // namespace rosidl_typesupport_cpp
```

This header is the shared contract on **both sides**:

| Who includes it | Role |
| --- | --- |
| **Callers** (`rclcpp`, your node) | Compile against the declaration; call `get_message_type_support_handle<demo_pkg::msg::DemoStatus>()` with a known type. |
| **Generated typesupport** (`build/demo_pkg/rosidl_typesupport_cpp/.../demo_status__type_support.cpp`) | Includes the same header and emits the matching `template<>` specialization into `libdemo_pkg__rosidl_typesupport_cpp.so`. |

Per-message package headers (e.g. `demo_pkg/msg/detail/demo_status__type_support.hpp`) also include the generic declaration and forward-declare the separate `extern "C"` macro entry. The generated `.cpp` defines **both** entry points; they return the same dispatcher handle pointer but are **different symbols**:

| Entry path | Symbol / call site | Linker name |
| --- | --- | --- |
| Typed C++ | `rosidl_typesupport_cpp::get_message_type_support_handle<demo_pkg::msg::DemoStatus>()` | C++ mangled specialization |
| Macro / `dlsym` | `ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_cpp, demo_pkg, msg, DemoStatus)` | `rosidl_typesupport_cpp__get_message_type_support_handle__demo_pkg__msg__DemoStatus` |

The generic template declaration is the **key** for typed C++: callers compile against one API; the linker binds each `Msg` type to its specialization in `libdemo_pkg__rosidl_typesupport_cpp.so`. That is unrelated to the stable `extern "C"` name used for dynamic loading — except that the macro body may call the specialization internally.

For each message the generator defines the template specialization:

```cpp
#include "rosidl_typesupport_cpp/message_type_support.hpp"

template<>
const rosidl_message_type_support_t *
get_message_type_support_handle<demo_pkg::msg::DemoStatus>()
{
  return &::demo_pkg::msg::rosidl_typesupport_cpp::DemoStatus_message_type_support_handle;
}
```

And a separate macro entry that returns the **same pointer** through a different symbol:

```cpp
extern "C"
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
  rosidl_typesupport_cpp, demo_pkg, msg, DemoStatus)()
{
  return get_message_type_support_handle<demo_pkg::msg::DemoStatus>();
}
```

`rclcpp` links against the template specialization. Tools that `dlsym` the macro never see the mangled name — they only need the predictable `extern "C"` string.

FastDDS and introspection follow the same pattern with their own declaration headers — `rosidl_typesupport_fastrtps_cpp/message_type_support_decl.hpp` and `rosidl_typesupport_introspection_cpp/message_type_support_decl.hpp` — each paired with per-message specializations in the corresponding package `.so`:

```cpp
rosidl_typesupport_cpp::get_message_type_support_handle<demo_pkg::msg::DemoStatus>();
rosidl_typesupport_fastrtps_cpp::get_message_type_support_handle<demo_pkg::msg::DemoStatus>();
rosidl_typesupport_introspection_cpp::get_message_type_support_handle<demo_pkg::msg::DemoStatus>();
```

Each returns that layer's static handle when the corresponding library is linked into the process.

| Question | C track | C++ track |
| --- | --- | --- |
| How is the dispatcher handle obtained? | Macro only (`ROSIDL_GET_MSG_TYPE_SUPPORT` or linked call) | **Template** in typed C++ code, **or** macro |
| How are FastDDS / introspection handles obtained? | Macro via dispatcher `func` + `dlsym` | **Template** when linked, **or** macro via dispatcher `func` + `dlsym` |
| Who uses templates? | Nobody | Typed C++ with link-time dependency on each layer's library |
| Who uses macros / `dlsym`? | Everyone on the C track | Dispatch map resolution, dynamic tools, Python/C callers, and any cross-`.so` load |

**When `rclcpp` uses templates:** `rclcpp::Publisher<demo_pkg::msg::DemoStatus>` typically calls `rosidl_typesupport_cpp::get_message_type_support_handle<...>()` first — a direct linked call, type-checked, not `dlsym`-able. It can also call the FastDDS or introspection templates directly when those libraries are linked; in practice publish/subscribe usually goes dispatcher → `func` → implementation.

**When macros still matter on the C++ track:** the dispatch map stores macro symbol **strings** for FastDDS and introspection. Resolving an implementation through `handle->func(...)` — or loading a typesupport `.so` that was not linked at build time — always uses `extern "C"` names and `dlsym`, even on the C++ track.

**Rule of thumb:** C++ with a known message type and the layer's library linked → template (`rosidl_typesupport_cpp::`, `rosidl_typesupport_fastrtps_cpp::`, or `rosidl_typesupport_introspection_cpp::get_message_type_support_handle<Msg>()`). String identifier, Python, C API, or lazy-loading an implementation through the dispatcher's `func` → `extern "C"` macro names and `dlsym`.

---

## Summary: type erasure in ROS 2

[Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html) separates **binding** (fixed at compile or construction time) from **dispatch** (runtime redirection through function pointers of the **same signature**). ROS 2 message typesupport is a large-scale instance of that pattern. It does not introduce a third mechanism — it combines the two basic ways Part I described to produce uniform entry points and per-type bodies:

| Part I actualization | ROS 2 analogue |
| --- | --- |
| Template — compiler emits different functions, **same signature** | `get_message_type_support_handle<Msg>()`, per-message `template<>` specializations; `cdr_serialize(const void *, …)` in generated callback tables |
| Manually written / generated non-template functions, **same signature** | Macro-expanded `extern "C"` entry symbols (`rosidl_typesupport_*__get_message_type_support_handle__…`); `ROSIDL_GET_MSG_TYPE_SUPPORT`; shared runtime resolvers (`handle->func`) |

**Binding at compile time.** `rosidl_generate_interfaces()` fixes the layout before the node runs. For each message and layer, generators emit either a template specialization or a macro-named `extern "C"` function — always returning `const rosidl_message_type_support_t *` or operating on `void *`, never exposing the concrete C++ type through the uniform interface. Per-message bodies differ; the **signatures** do not. After linking, typed C++ is bound to a specific specialization; macro symbol strings are baked into dispatch maps. Binding is complete before publish.

**Dispatch at runtime.** Middleware holds `rosidl_message_type_support_t` handles and `void *` message pointers. `handle->func` redirects to another function pointer of the same resolver signature; the map's lazy `dlopen`/`dlsym` selects which macro entry to call; `callbacks->cdr_serialize` redirects again through a function pointer with a uniform `(const void *, Cdr &)` shape. That is the Part I rule: **dispatch is redirection between functions that share a signature** — not re-binding to a new C++ type at runtime.

**What is erased.** The RMW, `rclpy`, and generic tools do not carry `demo_pkg::msg::DemoStatus` as a compile-time type. They see erased handles, string identifiers, and untyped pointers, while create/destroy/serialize are supplied explicitly by generated code — as in [Part III](https://shan-weiqiang.github.io/2025/07/09/type-erasure-part-three.html).

ROS 2 adds **library-scale structure** on top of Part I's core — four layers (definition, dispatcher, FastDDS, introspection), dual C/C++ tracks, package `.so` files versus per-message symbols — but the underlying type-erasure engine is unchanged: **template-generated and macro-generated functions with the same signature**, bound at compile time, dispatched at runtime through function pointers.

For a related static-generation design, see [Protobuf Reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html). JSON's runtime model is in [Type systems and JSON](https://shan-weiqiang.github.io/2025/08/10/type-system-json.html).

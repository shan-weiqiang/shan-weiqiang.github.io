---
layout: post
title:  "ROS 2 Generated Message Runtime Dependencies"
date:   2026-08-01 09:00:00 +0800
tags: [ros2, systems]
---

* toc
{:toc}

A ROS 2 interface package generates many artifacts: C structs, C++ classes, Python modules, lifecycle functions, conversion functions, generic typesupport dispatchers, serialization callbacks, and introspection metadata. An application rarely needs all of them at once.

The required runtime libraries depend on two questions:

1. Which language consumes the message: C, C++, or Python?
2. What does the application do: access fields, inspect metadata, serialize, or publish and subscribe?

This guide answers those questions by usage profile. It complements [Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html), which explains the dispatcher and concrete typesupport handles, and [Python/C VI — ROS 2 Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html), which explains the generated Python binding stack in detail.

## Scope and naming

The examples assume:

- Linux and ELF shared libraries;
- generated ROS 2 interfaces;
- Fast DDS / Fast RTPS as the concrete serialization example;
- the C typesupport track for C and Python;
- the C++ typesupport track for native C++.

Exact filenames depend on the ROS 2 distribution, interface package, Python version, platform, and selected RMW implementation. In the diagrams, names such as `package typesupport_c.so` are role names. A real package named `arm_control` normally installs files such as:

```text
libarm_control__rosidl_generator_c.so
libarm_control__rosidl_generator_py.so
libarm_control__rosidl_typesupport_c.so
libarm_control__rosidl_typesupport_cpp.so
libarm_control__rosidl_typesupport_fastrtps_c.so
libarm_control__rosidl_typesupport_fastrtps_cpp.so
libarm_control__rosidl_typesupport_introspection_c.so
libarm_control__rosidl_typesupport_introspection_cpp.so
```

ROS 2 does not normally generate a package-specific `rosidl_generator_cpp` shared library. Generated C++ message definitions are header-based.

### Notation

```text
→   Directly linked or imported
⇒   Automatically loaded through ELF DT_NEEDED
⇢   Selected and loaded at runtime through dlopen/dlsym
··  Called through a function pointer or Python PyCapsule
```

Generated headers are compile-time dependencies, not runtime dependencies. Likewise, a library appearing in an install tree does not imply that every application maps it into its process.

## The three runtime layers

Before looking at usage profiles, separate three generated roles:

| Layer | Typical generated artifact | Responsibility |
| --- | --- | --- |
| Message representation | C generator library, C++ headers, Python module | Object layout, fields, lifecycle, and language-facing API |
| Generic dispatcher | `rosidl_typesupport_c` or `_cpp` package library | Maps a generic message handle to an implementation identifier |
| Concrete implementation | Fast RTPS or introspection package library | Serialization callbacks or field metadata |

The dispatcher does not serialize a message. Its generated map records implementation identifiers, symbol names, and cached library handles. When native middleware requests an identifier such as `rosidl_typesupport_fastrtps_c`, the generic resolver loads the corresponding package library and returns its concrete handle.

This gives a common pattern:

```text
application
  → package dispatcher
    ⇒ generic resolver
    ⇢ package concrete implementation
      ⇒ implementation runtime
```

For example, when a C application serializes `arm_control/msg/PosCmd` using Fast RTPS typesupport:

```text
C application
  → libarm_control__rosidl_typesupport_c.so
      package dispatcher for arm_control messages
    ⇒ librosidl_typesupport_c.so
        generic identifier-based resolver
    ⇢ libarm_control__rosidl_typesupport_fastrtps_c.so
        generated PosCmd-specific serialization callbacks
      ⇒ librosidl_typesupport_fastrtps_c.so
          shared ROS 2 Fast RTPS typesupport infrastructure
      ⇒ libfastcdr.so
          reusable CDR byte encoder and decoder
```

The package concrete implementation contains code or metadata generated for a particular interface package. The implementation runtime contains reusable machinery shared by concrete libraries from many packages. For introspection, the equivalent runtime is `librosidl_typesupport_introspection_c.so`; for Fast RTPS serialization, it includes `librosidl_typesupport_fastrtps_c.so` and `libfastcdr.so`.

The requested concrete implementation is contextual:

- explicit metadata access requests introspection;
- Fast DDS publishing or RMW serialization requests Fast RTPS typesupport;
- another RMW can request a different implementation.

## Profile 1 — Message fields only

The application only constructs a message and reads or writes its fields. It does not request middleware typesupport, serialization, or introspection.

### C

```text
C application
├── generated C headers
│      structure layout and declarations
└→ package generator_c.so
   │  init/fini/create/destroy and nested lifecycle code
   ⇒ rosidl_runtime_c.so
      strings, sequences, and runtime helpers
```

A primitive-only message can sometimes be stack-allocated and accessed using headers alone. That is a narrow case. Generated initialization and finalization functions are the safe general interface, especially when a message contains:

- strings;
- bounded or unbounded sequences;
- arrays requiring element lifecycle;
- nested messages.

For general C message use, include the package's generated C library.

### C++

```text
C++ application
└── generated C++ headers
    class definition, constructors, containers, and field access
```

The generated C++ message class is header-based. Its constructors, field types, allocator-aware containers, and named-type helpers are emitted in headers, so field-only use does not require a package-specific generator shared library.

The C++ standard library and any libraries used by nested field types remain ordinary runtime dependencies of the application, but there is no generated `generator_cpp.so` counterpart to the C generator library.

### Python

```text
Python interpreter
└→ generated Python modules
    message class, validation, construction, and field operations
```

Native typesupport is not needed merely to instantiate a generated Python message and manipulate its fields. Before the generated metaclass method `__import_type_support__()` runs, the five native capsule slots remain `None`:

```python
_CREATE_ROS_MESSAGE = None
_CONVERT_FROM_PY = None
_CONVERT_TO_PY = None
_TYPE_SUPPORT = None
_DESTROY_ROS_MESSAGE = None
```

The pure Python object exists independently of a native `rosidl_message_type_support_t` handle. Native capsules become necessary when `rclpy` needs to create a C message, convert between Python and C, obtain typesupport, or destroy the C object.

## Profile 2 — Runtime introspection

Runtime introspection means obtaining generated metadata such as field names, field types, byte offsets, array and sequence properties, nested type references, and generic access callbacks.

Introspection is not automatically required for ordinary field access. It is a concrete typesupport implementation selected when a native caller explicitly requests its identifier or when a middleware/tooling path is designed around introspection.

### C

```text
C application
→ package typesupport_c.so
  │  generated package/type dispatch map
  ⇒ librosidl_typesupport_c.so
  │  generic resolver
  ⇢ package introspection_c.so
    ⇒ librosidl_typesupport_introspection_c.so
```

Add `generator_c.so` when the same application creates, initializes, finalizes, or destroys C messages.

The generated macro supplies the package dispatcher handle:

```c
const rosidl_message_type_support_t * generic_handle =
  ROSIDL_GET_MSG_TYPE_SUPPORT(arm_control, msg, PosCmd);
```

An explicit introspection consumer conceptually asks the dispatcher for:

```text
rosidl_typesupport_introspection_c
```

The resolver then loads the package introspection library and returns a handle whose `data` points to generated `MessageMembers` metadata.

Loading the generic typesupport dispatcher does not automatically load introspection. The introspection library is loaded only when a native consumer explicitly requests the `rosidl_typesupport_introspection_c` identifier. Normal publishing usually requests the selected RMW's serialization typesupport instead.

### C++

```text
C++ application
→ package typesupport_cpp.so
  ⇒ librosidl_typesupport_cpp.so
  ⇢ package introspection_cpp.so
    ⇒ librosidl_typesupport_introspection_cpp.so
```

Generated C++ code provides a template specialization for the message type:

```cpp
const rosidl_message_type_support_t * generic_handle =
  rosidl_typesupport_cpp::get_message_type_support_handle<MessageT>();

const rosidl_message_type_support_t * introspection_handle =
  rosidl_typesupport_cpp::get_message_typesupport_handle_function(
    generic_handle,
    rosidl_typesupport_introspection_cpp::typesupport_identifier);
```

The first call reaches the package's generic C++ dispatcher. The second requests the concrete introspection C++ handle. That handle contains the generated metadata for `MessageT`.

### Python

```text
Python application
→ generated Python modules
→ package Python typesupport extension
  ⇒ Python runtime library, where dynamically linked
  ⇒ package generator_py.so
  ⇒ package generator_c.so, directly or transitively
  ⇒ package typesupport_c.so
     ⇒ librosidl_typesupport_c.so
     ⇢ package introspection_c.so
       ⇒ librosidl_typesupport_introspection_c.so
```

The extension filename and Python runtime dependency vary by distribution and build. For example, Humble commonly uses Python 3.10, while Jazzy commonly uses Python 3.12. Do not hard-code `libpython3.10.so.1.0` as a cross-distribution dependency.

Python imports the package's C typesupport extension to populate its capsules. The extension exposes the generic C dispatcher handle. The introspection library itself is loaded only if downstream native code asks that dispatcher for the introspection C identifier. Normal Python application code does not call `dlopen` directly.

## Profile 3 — Serialization and deserialization

Serialization requires a concrete wire-format implementation. The following examples use Fast RTPS typesupport and Fast CDR. A different RMW or explicit serializer can select another concrete backend.

### C

The direct C trigger uses an initialized `rmw_serialized_message_t` buffer and the generated C dispatcher handle:

```c
const rosidl_message_type_support_t * type_support =
  ROSIDL_GET_MSG_TYPE_SUPPORT(arm_control, msg, PosCmd);

rmw_serialize(&message, type_support, &serialized);
rmw_deserialize(&serialized, type_support, &restored_message);
```

The message-specific dependency chain is:

```text
C application
├→ package generator_c.so
│   C message lifecycle
├→ package typesupport_c.so
│   ⇒ librosidl_typesupport_c.so
│   ⇢ package fastrtps_c.so
│      ⇒ librosidl_typesupport_fastrtps_c.so
│      ⇒ libfastcdr.so
└→ librmw.so and selected RMW implementation
```

`rmw_serialize()` is an RMW API, so the process also needs the RMW runtime and selected implementation. The package dispatcher is the message-specific front door; the active RMW requests the concrete serialization handle.

### C++

`rclcpp::Serialization<MessageT>` obtains the message handle through the generated C++ specialization:

```cpp
rclcpp::Serialization<arm_control::msg::PosCmd> serialization;
rclcpp::SerializedMessage serialized;

serialization.serialize_message(&message, &serialized);
serialization.deserialize_message(&serialized, &restored_message);
```

```text
C++ application
├── generated C++ headers
├→ package typesupport_cpp.so
│   ⇒ librosidl_typesupport_cpp.so
│   ⇢ package fastrtps_cpp.so
│      ⇒ librosidl_typesupport_fastrtps_cpp.so
│      ⇒ libfastcdr.so
└→ rclcpp/rcl/rmw serialization runtime
```

There is still no package generator C++ shared library. The package-specific runtime dependency is the C++ dispatcher and whichever concrete implementation it resolves.

### Python

```text
Python application
├→ generated Python modules
├→ package Python typesupport extension
│   ├⇒ package generator_py.so
│   ├⇒ package generator_c.so
│   └⇒ package typesupport_c.so
│      ⇒ librosidl_typesupport_c.so
│      ⇢ package fastrtps_c.so
│         ⇒ librosidl_typesupport_fastrtps_c.so
│         ⇒ libfastcdr.so
└→ rclpy native extension
    ⇒ librcl.so
    ⇒ librmw.so
    ⇒ selected RMW implementation
```

Python serialization first converts the Python object into its generated C representation, then passes the generic C typesupport handle into the native ROS 2 stack. The selected RMW resolves the concrete serialization callbacks.

## Profile 4 — Full publish and subscribe

Publish/subscribe adds client-library, RCL, RMW, discovery, transport, and middleware dependencies to the message-specific layers.

### C

```text
C application
├→ librcl.so
├→ librmw.so
├→ selected RMW implementation
├→ package generator_c.so
└→ package typesupport_c.so
    ⇒ librosidl_typesupport_c.so
    ⇢ package fastrtps_c.so
       ⇒ librosidl_typesupport_fastrtps_c.so
       ⇒ libfastcdr.so
```

The publisher control flow is:

```text
ROSIDL_GET_MSG_TYPE_SUPPORT(package, msg, Message)
    ↓ generic package typesupport_c handle
rcl_publisher_init(..., type_support, ...)
    ↓
rmw_create_publisher(..., type_support, ...)
    ↓ selected RMW resolves its concrete typesupport

rcl_publish(&publisher, &message, ...)
    ↓
rmw_publish(...)
    ↓ concrete typesupport serializes the message
middleware sends the serialized data
```

### C++

```text
C++ application
├→ librclcpp.so
│   ⇒ librcl.so
│   ⇒ librmw.so
│   ⇒ selected RMW implementation
└→ package typesupport_cpp.so
    ⇒ librosidl_typesupport_cpp.so
    ⇢ package fastrtps_cpp.so
       ⇒ librosidl_typesupport_fastrtps_cpp.so
       ⇒ libfastcdr.so
```

The generated specialization connects `MessageT` to the package dispatcher:

```text
rclcpp::create_publisher<MessageT>()
    ↓ get_message_type_support_handle<MessageT>()
    ↓ specialization from package typesupport_cpp.so
rcl_publisher_init(..., type_support, ...)
    ↓
rmw_create_publisher(..., type_support, ...)
    ↓ selected RMW resolves concrete typesupport

publisher->publish(message)
    ↓
rclcpp → rcl_publish()
    ↓
rmw_publish(...)
    ↓ concrete typesupport serializes the message
middleware sends the serialized data
```

### Python

```text
Python application
├→ rclpy
├→ _rclpy_pybind11...so
│   ⇒ librcl.so
│   ⇒ librmw.so
│   ⇒ selected RMW implementation
├→ generated Python message package
└→ package Python typesupport extension
    ├⇒ package generator_py.so
    ├⇒ package generator_c.so
    └⇒ package typesupport_c.so
       ⇒ librosidl_typesupport_c.so
       ⇢ package fastrtps_c.so
          ⇒ librosidl_typesupport_fastrtps_c.so
          ⇒ libfastcdr.so
```

The Python client library and generated message binding are separate native stacks. `rclpy` owns the node, publisher, subscription, QoS, and calls into `rcl`/`rmw`. The generated package owns Python-to-C conversion and the message-specific typesupport capsules. They meet when native `rclpy` reads those capsules from the message class.

## How Python exposes native message functions

Generated Python message classes use five attributes:

```python
_CREATE_ROS_MESSAGE
_CONVERT_FROM_PY
_CONVERT_TO_PY
_TYPE_SUPPORT
_DESTROY_ROS_MESSAGE
```

These are not ordinary Python callables. After `__import_type_support__()` runs, they are Python-visible wrappers around native pointers.

### Step 1 — Wrap a native pointer in `PyCapsule`

The generated Python typesupport extension creates capsules for its C functions and handles. Conceptually:

```c
PyObject * capsule = PyCapsule_New(
  (void *)&arm_control__msg__pos_cmd__convert_from_py,
  NULL,
  NULL);

PyModule_AddObject(
  pymodule,
  "convert_from_py_msg__msg__pos_cmd",
  capsule);
```

The generated metaclass imports the extension and stores the capsule:

```python
cls._CONVERT_FROM_PY = module.convert_from_py_msg__msg__pos_cmd
```

This assignment does not invoke the native conversion function. It only places the opaque capsule object on the message metaclass.

```text
generated C conversion function
    ↓ take address
C function pointer
    ↓ PyCapsule_New
Python PyCapsule
    ↓ assign to metaclass
PosCmd.__class__._CONVERT_FROM_PY
```

A capsule is intentionally not callable from pure Python:

```python
capsule = PosCmd.__class__._CONVERT_FROM_PY
print(type(capsule))
# <class 'PyCapsule'>

capsule()
# TypeError: 'PyCapsule' object is not callable
```

### Step 2 — Native `rclpy` extracts and invokes the pointer

High-level Python code can call:

```python
payload = serialize_message(message)
```

The Python path checks that the message type has imported its support module, then calls the native `_rclpy` extension with the message object and type.

Native code conceptually obtains the capsule through the message class or its metaclass, extracts the pointer, casts it to the expected signature, and invokes it:

```cpp
py::object capsule = message_type.attr("_CONVERT_FROM_PY");

void * raw_pointer = PyCapsule_GetPointer(capsule.ptr(), NULL);

using convert_from_py_function = bool (*)(PyObject *, void *);
auto convert_from_py =
  reinterpret_cast<convert_from_py_function>(raw_pointer);

bool success = convert_from_py(python_message, c_message);
```

The exact native source differs across ROS 2 versions, but the ABI pattern is stable:

```text
generated native function
    ↓ wrapped in PyCapsule
generated message class attribute
    ↓ read by native rclpy
PyCapsule_GetPointer
    ↓ cast to expected signature
native function-pointer call
```

The five attributes provide five different native capabilities:

| Attribute | Native role |
| --- | --- |
| `_CREATE_ROS_MESSAGE` | Allocate and initialize a generated C message |
| `_CONVERT_FROM_PY` | Copy/convert a Python message into an existing C message |
| `_CONVERT_TO_PY` | Convert a C message into a Python message object |
| `_TYPE_SUPPORT` | Expose the generic `rosidl_message_type_support_t` handle |
| `_DESTROY_ROS_MESSAGE` | Finalize and free the generated C message |

Pure Python code imports, stores, and passes these objects. Native `rclpy` interprets their pointer payloads and performs the actual calls.

## Nested-message dependency expansion

Dependencies expand recursively. If package A contains a field whose type comes from package B, the relevant generated libraries from B enter A's link or runtime closure:

```text
A generator_c
    ⇒ B generator_c
       when B lifecycle code is needed

A fastrtps_c/cpp
    ⇒ B fastrtps_c/cpp
       for nested serialization
    ⇒ relevant B generator libraries

A introspection_c/cpp
    ⇒ B introspection_c/cpp
       for nested metadata
    ⇒ relevant B generator libraries
```

The same rule applies recursively through messages, services, and actions. A deployment cannot copy only the top-level package libraries if its generated interfaces reference types from other packages. It needs the transitive closure for the capabilities it actually uses.

For example, a top-level message may require:

- package A's dispatcher;
- package A's Fast RTPS implementation;
- package B's Fast RTPS implementation for a nested field;
- package B's generated C lifecycle library;
- `rosidl_runtime_c`, Fast CDR, and the selected RMW runtime.

The closure is capability-specific: field-only C++ use can remain header-only even when serialization of the same nested type requires several shared libraries.

## Dependency matrix

The profiles can be summarized as follows:

| Usage | C | C++ | Python |
| --- | --- | --- | --- |
| Fields only | Headers + usually `generator_c` | Generated headers | Generated Python modules |
| Introspection | C dispatcher + introspection C | C++ dispatcher + introspection C++ | Python extension + C dispatcher + introspection C |
| Serialization | C lifecycle + C dispatcher + concrete C serializer + RMW | Headers + C++ dispatcher + concrete C++ serializer + runtime | Python extension + conversion libs + C dispatcher + concrete C serializer + `rclpy`/RMW |
| Publish/subscribe | `rcl`/`rmw` + C message stack | `rclcpp`/`rcl`/`rmw` + C++ message stack | `rclpy` native stack + generated Python/C message stack |

The key conclusions are:

1. Generated headers do not imply runtime shared-library dependencies.
2. C++ message representation is header-based; C and Python rely on generated native lifecycle/conversion libraries for general use.
3. The generic typesupport library is a dispatcher, not the serializer or metadata implementation.
4. Concrete Fast RTPS or introspection libraries are selected by identifier and loaded on demand.
5. Python message classes transport native function pointers through `PyCapsule`; native `rclpy` performs the calls.
6. Nested interfaces expand every selected capability into a recursive package dependency closure.

In short:

> Choose runtime dependencies by capability, language track, selected RMW implementation, and recursive field closure—not by copying every generated library from the interface package.

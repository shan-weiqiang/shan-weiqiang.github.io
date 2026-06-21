---
layout: post
title:  "Python C Extensions: Part VI — ROS 2 Message Bindings"
date:   2026-06-20 14:00:00 +0800
tags: [python]
---

* toc
{:toc}

This article is Part VI of the Python C extension series. [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) introduced `PyCapsule` as an opaque handle for C pointers (§2.1). Parts II–V covered execution models, ctypes, and handle pools. [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) covers compile-time C++ bindings and contrasts them with ctypes. Here we apply the capsule pattern at production scale: how **ROS 2 Jazzy** generates Python message bindings, the typesupport dispatcher pattern, and how `rclpy` interacts with message typesupport at publish time — including `_rclpy_pybind11` as a real pybind11 module (see Part VII §11.1).

All paths, filenames, and CMake behavior below come from building [`ros2_binding_demo`](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) on **ROS 2 Jazzy** (Ubuntu 24.04 Noble, Python 3.12, `aarch64`).

For the C-side typesupport dispatcher, see [Type Erasure Part IV — ROS 2 Message Type System](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html). Part VI walks the **Python-specific** layers in full detail.

Runnable demo: [ros2_binding_demo](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) in the [python](https://github.com/shan-weiqiang/python) repository.

```bash
source /opt/ros/jazzy/setup.zsh
cd ros2_binding_demo
colcon build --cmake-args \
  -DPython3_EXECUTABLE=$(which python3) \
  -DPYTHON_EXECUTABLE=$(which python3)
source install/setup.zsh
python3 verify_bindings.py
```

| Section | Demo folder |
|---|---|
| §10.1–10.8 | [ros2_binding_demo](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) — [`src/demo_pkg/`](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo/src/demo_pkg), [`verify_bindings.py`](https://github.com/shan-weiqiang/python/blob/main/ros2_binding_demo/verify_bindings.py) |

---

## Section 10: ROS 2 Python Message Bindings

### Overview

ROS 2 Jazzy uses a layered architecture for Python bindings, separating pure Python classes, C conversion functions, and typesupport implementations. This section covers the binding architecture, the dispatcher pattern, and how `rclpy` interacts with message typesupport — using artifacts from a real `colcon build` of `demo_pkg`.

All examples use `demo_pkg/msg/DemoStatus` from the demo workspace — the same package as [Type Erasure Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html).

---

### 10.1 Colcon build: Python version on Jazzy

On Jazzy, `rosidl_generator_py` builds Python bindings through CMake **`FindPython3`** (`python3_add_library`, `PYTHON_INSTALL_DIR` under `lib/python3.12/site-packages`). Pass both cmake hints to the interpreter you will run after `source install/setup.*`:

```bash
colcon build --cmake-args \
  -DPython3_EXECUTABLE=$(which python3) \
  -DPYTHON_EXECUTABLE=$(which python3)
```

> **Reminder — two variables, two roles (especially on older ROS 2 such as Humble):** `Python3_EXECUTABLE` picks the **install path** (`lib/python3.X/site-packages`); `PYTHON_EXECUTABLE` picks the **extension ABI** (headers, linker flags, and on older distros the `cpython-*` filename suffix). On Jazzy both should still be set to the same binary. If only one is set, install path and extension build can diverge:
>
> | Configuration | Install path | Extension ABI / filename | Result |
> |---|---|---|---|
> | `-DPython3_EXECUTABLE=/usr/bin/python3.11` only | `python3.11/site-packages` | Built against default `python3.10` → `cpython-310-*.so` | **Mismatch** |
> | `-DPYTHON_EXECUTABLE=/usr/bin/python3.11` only | Default `python3.10/site-packages` | `cpython-311-*.so` | **Mismatch** |
> | Both set to the same interpreter | Consistent | Consistent | **Correct** |

After `source install/setup.zsh`:

```bash
python3 --version
# Python 3.12.3

python3 -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))"
# cpython-312-aarch64-linux-gnu
```

#### How Jazzy names the built artifacts

`python3_add_library` builds Layer-3 typesupport wrappers. On our Jazzy build it emits **plain `.so` names** (no `cpython-*` tag in the filename):

```cmake
set(_target_name "${PROJECT_NAME}_s__${_typesupport_impl}")
python3_add_library(${_target_name} MODULE
  ${_generated_extension_${_typesupport_impl}_files})
```

Installed result:

```text
install/demo_pkg/lib/python3.12/site-packages/demo_pkg/
  demo_pkg_s__rosidl_typesupport_c.so
```

Python still imports this as `demo_pkg.demo_pkg_s__rosidl_typesupport_c`. The internal `PyModuleDef` name created at runtime is `_demo_pkg_support` — that string is **not** the import path.

By contrast, `rclpy`'s pybind11 module **does** carry the SOABI tag on Jazzy:

```text
/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/
  _rclpy_pybind11.cpython-312-aarch64-linux-gnu.so
```

`rosidl_generator_py` and `rclpy` therefore use different extension naming conventions on the same distribution. Version isolation for message bindings relies on installing into `lib/python3.12/site-packages/` rather than on a `cpython-*` filename suffix.

---

### 10.2 Three-layer binding architecture

ROS 2 Python message bindings split into three layers.

#### Layer 1: Pure Python class

**File:** `demo_pkg/msg/_demo_status.py`

**Purpose:**

- Provides Python class definition (`DemoStatus`): `__repr__`, basic operations
- Metaclass defines `__import_type_support__()` method

**Capabilities:**

- Works **without** the Layer-3 `.so` (pure Python fallback)
- Can create instances and access fields

**Limitations:**

- Cannot serialize/deserialize to wire format until `__import_type_support__()` loads capsules from Layer 3
- `rclpy` publish/subscribe paths call `check_for_type_support`, which triggers import automatically

```python
from demo_pkg.msg import DemoStatus

msg = DemoStatus(name="x", code=1, active=True)
assert DemoStatus.__class__._TYPE_SUPPORT is None  # capsules not loaded yet
```

#### Layer 2: C conversion library

**File:** `libdemo_pkg__rosidl_generator_py.so`

**Characteristics:**

- Pure C shared library (no `cpython-*` suffix)
- **Not** a Python extension — not loaded by `import` directly
- Loaded by the Layer-3 Python extension wrapper via ELF `DT_NEEDED`

**Functions:**

- `demo_pkg__msg__demo_status__convert_from_py` — Python `DemoStatus` → C struct
- `demo_pkg__msg__demo_status__convert_to_py` — C struct → Python `DemoStatus`

**Dependencies:**

- Uses `Python.h` (`PyObject *` parameters)
- Must be compiled for the matching Python version

#### Layer 3: Python extension wrapper

**Three identical wrappers generated:**

| Source (build tree) | Installed under `site-packages/demo_pkg/` | Imported at runtime? |
|---|---|---|
| `_demo_pkg_s.ep.rosidl_typesupport_c.c` | `demo_pkg_s__rosidl_typesupport_c.so` | **Yes** |
| `_demo_pkg_s.ep.rosidl_typesupport_fastrtps_c.c` | `demo_pkg_s__rosidl_typesupport_fastrtps_c.so` | No |
| `_demo_pkg_s.ep.rosidl_typesupport_introspection_c.c` | `demo_pkg_s__rosidl_typesupport_introspection_c.so` | No |

`import_type_support('demo_pkg')` loads only the first file. The import path is `demo_pkg.demo_pkg_s__rosidl_typesupport_c`; the on-disk name has no `cpython-*` suffix on Jazzy.

**Characteristics:**

- Source code is **identical** (only `PyInit_*` function name differs)
- All three compiled from the same empy template
- Each links to a different C typesupport library at compile time (plus the dispatcher — see §10.6)
- Only the `typesupport_c` binding is imported by Python; the others are build artifacts

**Why three wrappers?**

- Build system generates all three from the same template
- Each links to a different C library → linker resolves `ROSIDL_GET_MSG_TYPE_SUPPORT` to different symbols at link time
- Python only needs `typesupport_c` (dispatcher) because the dispatcher handles runtime loading of FastDDS and introspection libraries
- fastrtps/introspection wrappers exist but are never imported by `import_type_support`

**Registered capsules (same pattern in all three):**

| Capsule attribute | Contents |
|---|---|
| `create_ros_message_msg__msg__demo_status` | `PyCapsule` wrapping function pointer to create C struct |
| `destroy_ros_message_msg__msg__demo_status` | `PyCapsule` wrapping function pointer to destroy C struct |
| `convert_from_py_msg__msg__demo_status` | `PyCapsule` wrapping Python → C conversion function pointer |
| `convert_to_py_msg__msg__demo_status` | `PyCapsule` wrapping C → Python conversion function pointer |
| `type_support_msg__msg__demo_status` | `PyCapsule` wrapping typesupport struct pointer (dispatcher for `typesupport_c`; FastDDS or introspection for the other two wrappers) |

Install tree after `colcon build` on Jazzy (`demo_pkg`):

```text
install/demo_pkg/lib/
  libdemo_pkg__rosidl_generator_py.so          # Layer 2 — C conversion
  libdemo_pkg__rosidl_typesupport_c.so         # dispatcher
  libdemo_pkg__rosidl_typesupport_fastrtps_c.so
  libdemo_pkg__rosidl_typesupport_introspection_c.so
  libdemo_pkg__rosidl_typesupport_cpp.so       # C++ track (not used by Python)
  libdemo_pkg__rosidl_typesupport_fastrtps_cpp.so
  libdemo_pkg__rosidl_typesupport_introspection_cpp.so
  libdemo_pkg__rosidl_generator_c.so
install/demo_pkg/lib/python3.12/site-packages/demo_pkg/
  demo_pkg_s__rosidl_typesupport_c.so          # Layer 3 — imported by Python
  demo_pkg_s__rosidl_typesupport_fastrtps_c.so # build artifact
  demo_pkg_s__rosidl_typesupport_introspection_c.so
  msg/_demo_status.py                          # Layer 1
```

---

### 10.3 Generated extension wrapper: five-section source structure

The C source for the dispatcher binding is at `build/demo_pkg/rosidl_generator_py/demo_pkg/_demo_pkg_s.ep.rosidl_typesupport_c.c`. It has five logical sections.

#### Section 1: Python module definition

The code first defines a Python module structure using the Python C API:

- `PyMethodDef demo_pkg__methods[]` — module methods (empty array; no callable methods)
- `PyModuleDef demo_pkg__module` — module structure with:
  - Module name: `"_demo_pkg_support"` (internal name seen by `PyModule_Create`)
  - Doc string: `"_demo_pkg_doc"`
  - State: `-1` (module keeps state in global variables)
  - Methods: empty array

This structure is used by `PyModule_Create()` to create the Python module object.

```c
static PyMethodDef demo_pkg__methods[] = {
  {NULL, NULL, 0, NULL}  /* sentinel */
};

static struct PyModuleDef demo_pkg__module = {
  PyModuleDef_HEAD_INIT,
  "_demo_pkg_support",
  "_demo_pkg_doc",
  -1,
  demo_pkg__methods,
  NULL, NULL, NULL, NULL,
};
```

#### Section 2: C includes and helper functions

The code includes ROS 2 C headers and defines wrapper functions:

- `rosidl_runtime_c/message_type_support_struct.h` — defines `rosidl_message_type_support_t`
- `demo_pkg/msg/detail/demo_status__struct.h` — C struct definition for `DemoStatus`
- `demo_pkg/msg/detail/demo_status__functions.h` — create/destroy functions

Helper wrapper functions:

```c
static void * demo_pkg__msg__demo_status__create_ros_message(void)
{
  return demo_pkg__msg__DemoStatus__create();
}

static void demo_pkg__msg__demo_status__destroy_ros_message(void * raw_ros_message)
{
  demo_pkg__msg__DemoStatus * ros_message = (demo_pkg__msg__DemoStatus *)raw_ros_message;
  demo_pkg__msg__DemoStatus__destroy(ros_message);
}
```

**Why wrapper functions are needed:**

- ROS 2 C functions have specific signatures (`DemoStatus__create()` returns a typed pointer)
- Wrappers match the signature expected by `rclpy` (returns `void *`, takes `void *`)
- These wrappers are wrapped in `PyCapsule` objects later

#### Section 3: External imports (symbols resolved by linker)

The code declares external functions — **not** defined in this file; resolved by the linker:

```c
ROSIDL_GENERATOR_C_IMPORT
bool demo_pkg__msg__demo_status__convert_from_py(PyObject * _pymsg, void * ros_message);

ROSIDL_GENERATOR_C_IMPORT
PyObject * demo_pkg__msg__demo_status__convert_to_py(void * raw_ros_message);

ROSIDL_GENERATOR_C_IMPORT
const rosidl_message_type_support_t *
ROSIDL_GET_MSG_TYPE_SUPPORT(demo_pkg, msg, DemoStatus);
```

| Symbol | Imported from |
|---|---|
| `demo_pkg__msg__demo_status__convert_from_py` | `libdemo_pkg__rosidl_generator_py.so` |
| `demo_pkg__msg__demo_status__convert_to_py` | `libdemo_pkg__rosidl_generator_py.so` |
| `ROSIDL_GET_MSG_TYPE_SUPPORT(demo_pkg, msg, DemoStatus)` | `libdemo_pkg__rosidl_typesupport_*.so` (which one depends on link target) |

**Key insight:** The linker resolves `ROSIDL_GET_MSG_TYPE_SUPPORT` to different functions depending on which C library is linked:

| Binding source | Primary typesupport link | `ROSIDL_GET_MSG_TYPE_SUPPORT` resolves to |
|---|---|---|
| `_demo_pkg_s.ep.rosidl_typesupport_c.c` | `libdemo_pkg__rosidl_typesupport_c.so` | Dispatcher typesupport |
| `_demo_pkg_s.ep.rosidl_typesupport_fastrtps_c.c` | `libdemo_pkg__rosidl_typesupport_fastrtps_c.so` | FastDDS serialization typesupport |
| `_demo_pkg_s.ep.rosidl_typesupport_introspection_c.c` | `libdemo_pkg__rosidl_typesupport_introspection_c.so` | Introspection typesupport |

On Jazzy, **all three wrappers also link** `libdemo_pkg__rosidl_typesupport_c.so` (dispatcher) in addition to their specific typesupport library.

#### Section 4: Registration function (creates and registers capsules)

`_register_msg_type__msg__demo_status(PyObject * pymodule)` creates five `PyCapsule` objects.

For each capsule, the pattern is:

1. Create capsule with `PyCapsule_New((void *)pointer, NULL, NULL)`
2. Add to module with `PyModule_AddObject(pymodule, "attribute_name", pyobject)`
3. Error handling: if `PyCapsule_New` or `PyModule_AddObject` fails, cleanup and return error

| Capsule name on module | Wraps | Source |
|---|---|---|
| `create_ros_message_msg__msg__demo_status` | `&demo_pkg__msg__demo_status__create_ros_message` | Local wrapper function |
| `destroy_ros_message_msg__msg__demo_status` | `&demo_pkg__msg__demo_status__destroy_ros_message` | Local wrapper function |
| `convert_from_py_msg__msg__demo_status` | `&demo_pkg__msg__demo_status__convert_from_py` | `libdemo_pkg__rosidl_generator_py.so` |
| `convert_to_py_msg__msg__demo_status` | `&demo_pkg__msg__demo_status__convert_to_py` | `libdemo_pkg__rosidl_generator_py.so` |
| `type_support_msg__msg__demo_status` | `ROSIDL_GET_MSG_TYPE_SUPPORT(...)` pointer | Linked typesupport library |

After registration, Python can access:

```python
module.create_ros_message_msg__msg__demo_status   # PyCapsule
module.destroy_ros_message_msg__msg__demo_status  # PyCapsule
module.convert_from_py_msg__msg__demo_status      # PyCapsule
module.convert_to_py_msg__msg__demo_status        # PyCapsule
module.type_support_msg__msg__demo_status         # PyCapsule
```

#### Section 5: PyInit entry point (Python import hook)

`PyInit_demo_pkg_s__rosidl_typesupport_c(void)` — entry point Python calls on import:

- `PyMODINIT_FUNC` — macro marking this as a Python module initialization function
- `PyModule_Create(&demo_pkg__module)` — creates module object from module definition
- `_register_msg_type__msg__demo_status(pymodule)` — registers capsules for each message
- `return pymodule` — returns module to Python

The **only** difference between the three binding source files is this function name:

- `PyInit_demo_pkg_s__rosidl_typesupport_c(void)`
- `PyInit_demo_pkg_s__rosidl_typesupport_fastrtps_c(void)`
- `PyInit_demo_pkg_s__rosidl_typesupport_introspection_c(void)`

#### How different bindings get different typesupport

The key is the `ROSIDL_GET_MSG_TYPE_SUPPORT` macro:

- The C compiler sees this macro and creates an undefined symbol reference
- The symbol is **not** defined in the extension source file
- The linker must find it in linked libraries

At compile time, CMake links each binding to different C libraries:

```cmake
foreach(_typesupport_impl ${_typesupport_impls})
  set(_target_name "${PROJECT_NAME}_s__${_typesupport_impl}")
  python3_add_library(${_target_name} MODULE
    ${_generated_extension_${_typesupport_impl}_files})
  target_link_libraries(${_target_name} PRIVATE
    ${_target_name_lib}                                    # lib*_rosidl_generator_py.so
    ${rosidl_generate_interfaces_TARGET}__${_typesupport_impl}  # specific typesupport
    ${c_typesupport_target}                                # dispatcher
    ...
  )
endforeach()
```

Result: same source code, three compilations, each `.so` embeds a different typesupport pointer in the `type_support_*` capsule at link time.

---

### 10.4 Import flow when Python loads the typesupport module

1. **Python finds** `install/demo_pkg/lib/python3.12/site-packages/demo_pkg/demo_pkg_s__rosidl_typesupport_c.so`
   - Import machinery resolves the logical name `demo_pkg.demo_pkg_s__rosidl_typesupport_c` to this file (plain `.so` suffix is valid on Python 3.12)
   - `dlopen` loads the shared library

2. **Python finds** `PyInit_demo_pkg_s__rosidl_typesupport_c` symbol
   - This is the entry point defined in Section 5

3. **Python calls** `PyInit_demo_pkg_s__rosidl_typesupport_c()`
   - Creates module object via `PyModule_Create`
   - Calls `_register_msg_type__msg__demo_status` (and other messages in the package)
   - Creates five `PyCapsule` objects per message
   - Adds them as module attributes
   - Returns module object

4. **Python stores** module with capsule attributes (all `PyCapsule`)

5. **Message metaclass stores capsules from module** (when `__import_type_support__()` runs):

```python
DemoStatus.__class__._CREATE_ROS_MESSAGE = module.create_ros_message_msg__msg__demo_status
DemoStatus.__class__._CONVERT_FROM_PY     = module.convert_from_py_msg__msg__demo_status
DemoStatus.__class__._CONVERT_TO_PY       = module.convert_to_py_msg__msg__demo_status
DemoStatus.__class__._TYPE_SUPPORT        = module.type_support_msg__msg__demo_status
DemoStatus.__class__._DESTROY_ROS_MESSAGE = module.destroy_ros_message_msg__msg__demo_status
```

6. **`rclpy` uses capsules when publishing:**
   - Gets capsules from `DemoStatus.__class__`
   - Unwraps `PyCapsule` objects to get C function pointers
   - Calls C functions to convert and publish

**Why this generated code is simple:**

- No actual conversion logic — all conversion done by external functions in `libdemo_pkg__rosidl_generator_py.so`
- No serialization logic — all serialization done by typesupport library (loaded dynamically by dispatcher)
- Just a wrapper — wraps existing C pointers in `PyCapsule` and exposes them to Python
- One template, three outputs — same code compiled three times, linked to different C libraries

#### Generated but unused bindings

The build system also generates Python bindings for fastrtps and introspection:

- `demo_pkg_s__rosidl_typesupport_fastrtps_c.so` — **not used** at runtime
- `demo_pkg_s__rosidl_typesupport_introspection_c.so` — **not used** at runtime

These are build artifacts, not runtime dependencies. Python only imports the `typesupport_c` binding; the dispatcher handles runtime loading of the others.

---

### 10.5 Typesupport dispatcher architecture

#### Dispatcher pattern overview

`libdemo_pkg__rosidl_typesupport_c.so` is a **dispatcher**, not a serializer. It dynamically loads fastrtps or introspection C libraries at runtime based on the RMW implementation.

**Dispatcher function:**

- `rosidl_typesupport_c__get_message_typesupport_handle_function`
- Takes: handle, identifier
- If identifier matches: return handle directly
- If different: load from shared library dynamically

**How it works:**

1. Check if requested typesupport identifier matches current
2. If different, use `rcpputils::SharedLibrary` to load the appropriate `.so`
3. Look up the typesupport function symbol in the loaded library
4. Return the appropriate `rosidl_message_type_support_t *`

Generated dispatcher code for `DemoStatus` (`build/demo_pkg/rosidl_typesupport_c/.../demo_status__type_support.cpp`):

```cpp
static const type_support_map_t _DemoStatus_message_typesupport_map = {
  2,
  "demo_pkg",
  &_DemoStatus_message_typesupport_ids.typesupport_identifier[0],
  &_DemoStatus_message_typesupport_symbol_names.symbol_name[0],
  &_DemoStatus_message_typesupport_data.data[0],
};

static const rosidl_message_type_support_t _DemoStatus_message_type_support_handle = {
  rosidl_typesupport_c__typesupport_identifier,
  reinterpret_cast<const type_support_map_t *>(&_DemoStatus_message_typesupport_map),
  rosidl_typesupport_c__get_message_typesupport_handle_function,
  ...
};
```

[Type Erasure Part IV](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) walks the full `dlopen` / `dlsym` chain.

#### Library loading chain

**Python imports:**

- `demo_pkg_s__rosidl_typesupport_c.so` — Python extension wrapper (Layer 3)

**Links to at compile time:**

- `libdemo_pkg__rosidl_generator_py.so` — conversion library (`convert_from_py`, `convert_to_py`)
- `libdemo_pkg__rosidl_typesupport_c.so` — dispatcher library

**Dispatcher dynamically loads at runtime:**

- `libdemo_pkg__rosidl_typesupport_fastrtps_c.so` — FastDDS serialization
- `libdemo_pkg__rosidl_typesupport_introspection_c.so` — introspection

**Key insight:** Python only imports the dispatcher binding. The dispatcher (C code) handles loading of actual serialization libraries at runtime.

#### Why all three binding source files are identical

The three Python binding source files differ only in `PyInit_*` function name:

- `_demo_pkg_s.ep.rosidl_typesupport_c.c`
- `_demo_pkg_s.ep.rosidl_typesupport_fastrtps_c.c`
- `_demo_pkg_s.ep.rosidl_typesupport_introspection_c.c`

**Why identical?** All generated from the same template; same capsule-registration functionality is needed regardless of which typesupport library supplies the `type_support_*` pointer.

**The magic at CMake compile time:**

```cmake
foreach(_typesupport_impl IN ITEMS
    rosidl_typesupport_c
    rosidl_typesupport_fastrtps_c
    rosidl_typesupport_introspection_c)
  target_link_libraries(${target_name}
    ${target_name_lib}              # lib*_rosidl_generator_py.so
    Python3::Python                 # libpython
    ${PROJECT_NAME}__${_typesupport_impl})  # KEY: different C library
endforeach()
```

Each Python binding links to its typesupport C library **and** the dispatcher (`__rosidl_typesupport_c`) per Jazzy's `target_link_libraries`. The linker resolves `ROSIDL_GET_MSG_TYPE_SUPPORT` based on the linked libraries.

---

### 10.6 Two bindings cooperating: `demo_pkg` + `rclpy`

Publishing a message touches **two independent Python binding stacks**. They are built separately, loaded separately, and meet only through `PyCapsule` handles on the message **class**:

| Binding | Package | Purpose | Python side | Native side |
|---|---|---|---|---|
| **Message binding** | `demo_pkg` (per interface package) | `DemoStatus` wire format: field marshalling, typesupport capsules | `_demo_status.py`, metaclass `__import_type_support__` | `demo_pkg_s__rosidl_typesupport_c.so` → `libdemo_pkg__rosidl_generator_py.so`, dispatcher `.so` |
| **Client library binding** | `rclpy` (single install) | ROS node API: publishers, `rcl_publish`, QoS | `node.py`, `publisher.py`, `type_support.py` | `_rclpy_pybind11.cpython-312-aarch64-linux-gnu.so` → `rcl` / `rmw` |

`rclpy` does **not** embed message conversion logic. It calls into the **message binding** at publish time by reading capsules that `demo_pkg` registered on `DemoStatus.__class__`.

#### Architecture: Python world vs C/C++ world

![ROS 2 message and rclpy bindings — Python world vs C/C++ world](/assets/images/python_c_ext_ros2_bindings_architecture.png)

Each numbered band is a strict top-to-bottom tier: pure Python at the top, Python C extensions in the middle, native C/C++ libraries at the bottom. Cross-tier arrows only point downward; capsule registration is noted on the message-binding module instead of drawing an upward edge back to the metaclass.

#### Publish flow (where the two bindings meet)

![ROS 2 publish flow — where demo_pkg message binding meets rclpy](/assets/images/python_c_ext_ros2_bindings_publish_flow.png)

---

### 10.7 Runnable verification

[`verify_bindings.py`](https://github.com/shan-weiqiang/python/blob/main/ros2_binding_demo/verify_bindings.py) checks twenty claims against the Jazzy-built workspace:

- Layer 2 `.so` under `lib/` has no `cpython-*` suffix; Layer 3 installs three plain `.so` wrappers under `lib/python3.12/site-packages/demo_pkg/`
- Pure Python instance construction with `_TYPE_SUPPORT is None`
- `import_type_support` loads only `demo_pkg_s__rosidl_typesupport_c.so`
- `__import_type_support__` fills five `PyCapsule` slots on the metaclass
- Generated C source contains `PyModuleDef`, register function, and `PyInit_demo_pkg_s__rosidl_typesupport_c`
- Dispatcher source contains `type_support_map_t` and the runtime resolver
- `nm -D` on the wrapper shows dispatcher and `PyInit` symbols
- `rclpy` publisher end-to-end publish succeeds

```bash
source /opt/ros/jazzy/setup.zsh
source install/setup.zsh
python3 verify_bindings.py
```

Expected: `20 passed, 0 failed`.

---

### 10.8 Jazzy artifact reference

Quick lookup for the names used throughout this article (from `ros2_binding_demo` built on Jazzy, Python 3.12, `aarch64`):

| Role | Path or symbol |
|---|---|
| Layer 1 pure Python | `install/.../site-packages/demo_pkg/msg/_demo_status.py` |
| Layer 2 conversion lib | `install/demo_pkg/lib/libdemo_pkg__rosidl_generator_py.so` |
| Layer 3 extension (used) | `install/.../site-packages/demo_pkg/demo_pkg_s__rosidl_typesupport_c.so` |
| Layer 3 extensions (unused) | `demo_pkg_s__rosidl_typesupport_fastrtps_c.so`, `..._introspection_c.so` |
| Dispatcher lib | `install/demo_pkg/lib/libdemo_pkg__rosidl_typesupport_c.so` |
| Generated C source | `build/demo_pkg/rosidl_generator_py/demo_pkg/_demo_pkg_s.ep.rosidl_typesupport_c.c` |
| `PyInit` symbol | `PyInit_demo_pkg_s__rosidl_typesupport_c` |
| Import path | `demo_pkg.demo_pkg_s__rosidl_typesupport_c` |
| `PyModuleDef` name | `_demo_pkg_support` |
| `rclpy` C extension | `_rclpy_pybind11.cpython-312-aarch64-linux-gnu.so` |
| Build interpreter SOABI | `cpython-312-aarch64-linux-gnu` (from `sysconfig`; not in `rosidl` Layer-3 filename) |

Python extension suffix search order on the build interpreter:

```python
importlib.machinery.EXTENSION_SUFFIXES
# ['.cpython-312-aarch64-linux-gnu.so', '.abi3.so', '.so']
```

`rosidl_generator_py` typesupport modules install as plain `.so` under `lib/python3.12/site-packages/`; Python loads them via the `.so` fallback entry. `rclpy`'s pybind11 module uses the tagged `cpython-312-aarch64-linux-gnu` suffix. Both are compiled against the same system Python — the difference is filename convention only. For how pybind11 builds such modules internally, see [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html).

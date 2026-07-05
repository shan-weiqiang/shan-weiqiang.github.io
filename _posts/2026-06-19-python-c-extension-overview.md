---
layout: post
title:  "Python/C I — PyTypeObject"
date:   2026-06-19 9:22:46 +0800
tags: [python]
---

* toc
{:toc}

This article covers the fundamentals of Python C extensions: writing extension functions and binding C structures to Python types. Companion articles: [Part II — Execution](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-execution.html) (interpreter model, bytecode vs C dispatch), [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) (FFI alternatives to hand-written extensions), [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) (ctypes mirroring, internal handles vs user API), [Part V — ctypes Handle Pool](https://shan-weiqiang.github.io/2026/06/20/python-c-ctypes-handle-pool.html) (C++ handle pool behind ctypes), [Part VI — ROS 2 Message Bindings](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) (ROS 2 `rosidl` capsule bindings and `rclpy`), [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) (compile-time C++ bindings, internals, contrast with ctypes), and [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html) (conceptual map — extension authoring vs binding patterns). Section 2 below uses "binding" for `PyTypeObject` exposure; Part VIII clarifies the broader distinction.

Runnable demos for every code example live in the [python](https://github.com/shan-weiqiang/python) repository. Build any C extension demo with `python3 setup.py build_ext --inplace` then run the matching `test_*.py`.

| Section | Demo folder |
|---|---|
| §1.1, §1.4 | [c_ext_spam_system](https://github.com/shan-weiqiang/python/tree/main/c_ext_spam_system) |
| §1.2 | [c_ext_exception_propagation](https://github.com/shan-weiqiang/python/tree/main/c_ext_exception_propagation) |
| §1.3 | [c_ext_reference_counting](https://github.com/shan-weiqiang/python/tree/main/c_ext_reference_counting) |
| §2.1 | [c_ext_capsule_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_capsule_config) |
| §2.2.2 | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) |
| §2.2.3 | [c_ext_config_nested](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_nested) |
| §2.3 | [c_ext_config_marshal](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_marshal) |
| §2 contrast (ctypes structs) | [ctypes_complex_struct](https://github.com/shan-weiqiang/python/tree/main/ctypes_complex_struct) — [Part IV](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) |
| §2.1 contrast (ROS 2 codegen) | [ros2_binding_demo](https://github.com/shan-weiqiang/python/tree/main/ros2_binding_demo) — [Part VI](https://shan-weiqiang.github.io/2026/06/20/python-c-extension-ros2-bindings.html) |
| §2.2.2 contrast (pybind11) | [c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config) — [Part VII](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) |

## Section 1: Python C Extension Fundamentals

### 1.1 Basic C Extension Function Structure

**Full source:** [c_ext_spam_system](https://github.com/shan-weiqiang/python/tree/main/c_ext_spam_system) — [`spam.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_spam_system/spam.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_spam_system/setup.py), [`test_spam.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_spam_system/test_spam.py)

A minimal extension function wraps a C library call and exposes it to Python. The canonical example from the official documentation wraps `system()`:

```c
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>

static PyObject *
spam_system(PyObject *self, PyObject *args)
{
    const char *command;
    int sts;

    if (!PyArg_ParseTuple(args, "s", &command))
        return NULL;
    sts = system(command);
    return PyLong_FromLong(sts);
}

static PyMethodDef SpamMethods[] = {
    {"system", spam_system, METH_VARARGS, "Execute a shell command."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef spammodule = {
    PyModuleDef_HEAD_INIT,
    "spam",
    "Spam module.",
    -1,
    SpamMethods
};

PyMODINIT_FUNC
PyInit_spam(void)
{
    return PyModule_Create(&spammodule);
}
```

```python
import spam

spam.system("true")   # 0
spam.system("false")  # non-zero exit status
```

**Function signature conventions:**

- **`self`**: For module-level functions, points to the module object. For methods on extension types, points to the instance .
- **`args`**: A pointer to a Python tuple containing positional arguments. Keyword arguments require [`PyArg_ParseTupleAndKeywords()`](https://docs.python.org/3/c-api/arg.html#c.PyArg_ParseTupleAndKeywords).
- **Return type**: Always `PyObject *`. Return `NULL` to signal an error (an exception must already be set). Return a non-`NULL` pointer on success.

**Argument parsing with [`PyArg_ParseTuple()`](https://docs.python.org/3/c-api/arg.html#c.PyArg_ParseTuple):**

- Parses Python arguments into C variables using a format string.
- Returns a non-zero value on success; returns `0` on failure and raises an appropriate exception.
- Common format codes: `s` (UTF-8 string), `i` (int), `f` (float), `O` (object), `|` (everything after this is optional).

**Return value construction:**

- `PyLong_FromLong()` — C `long` → Python `int`
- `PyUnicode_FromString()` — C string → Python `str`
- `Py_BuildValue()` — construct complex return values from a format string

### 1.2 Python Exception Handling in C Extensions

**Full source:** [c_ext_exception_propagation](https://github.com/shan-weiqiang/python/tree/main/c_ext_exception_propagation) — [`spam_errors.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exception_propagation/spam_errors.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exception_propagation/setup.py), [`test_spam_errors.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exception_propagation/test_spam_errors.py)

Python's exception model is based on a **per-thread global error state**, not per-module. When an exception is active, three fields in the current thread state hold the equivalent of `sys.exc_info()`:

- `exc_type` — the exception class (e.g., `ValueError`)
- `exc_value` — the exception instance
- `exc_traceback` — the traceback object

All three are `NULL` when no exception is set.

**Exception API functions:**

1. **Setting exceptions** (only where the error is first detected):
   - `PyErr_SetString(exc_type, message)` — set exception with a C string message
   - `PyErr_SetFromErrno(exc_type)` — construct value from `errno`
   - `PyErr_SetObject(exc_type, value)` — set exception with an arbitrary value

2. **Checking exceptions:**
   - `PyErr_Occurred()` — returns the current exception object, or `NULL` if none is set

3. **Clearing exceptions:**
   - `PyErr_Clear()` — clear the current exception; use only when handling it locally, not when propagating

**Error propagation pattern:**

```c
#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *SpamError = NULL;

/* Layer 3: deepest function — sets the specific error */
static PyObject *
layer3_func(PyObject *self, PyObject *args)
{
    int fail;
    if (!PyArg_ParseTuple(args, "i", &fail))
        return NULL;
    if (fail) {
        PyErr_SetString(SpamError, "Specific error: file not found");
        return NULL;
    }
    return PyLong_FromLong(42);
}

/* Layer 2: middle function — propagates and processes */
static PyObject *
layer2_func(PyObject *self, PyObject *args)
{
    PyObject *obj = layer3_func(self, args);
    if (obj == NULL)
        return NULL;  /* layer 3 already set the exception */
    long value = PyLong_AsLong(obj);
    Py_DECREF(obj);
    return PyLong_FromLong(value * 2);
}

/* Layer 1: top function — just propagates */
static PyObject *
layer1_func(PyObject *self, PyObject *args)
{
    PyObject *result = layer2_func(self, args);
    if (result == NULL)
        return NULL;
    return result;
}

static PyMethodDef SpamMethods[] = {
    {"call", layer1_func, METH_VARARGS, "Call through three C layers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef spammodule = {
    PyModuleDef_HEAD_INIT,
    "spam_errors",
    "Exception propagation demo.",
    -1,
    SpamMethods
};

PyMODINIT_FUNC
PyInit_spam_errors(void)
{
    PyObject *m = PyModule_Create(&spammodule);
    if (m == NULL)
        return NULL;

    SpamError = PyErr_NewException("spam_errors.SpamError", NULL, NULL);
    if (SpamError == NULL) {
        Py_DECREF(m);
        return NULL;
    }
    Py_INCREF(SpamError);
    if (PyModule_AddObject(m, "SpamError", SpamError) < 0) {
        Py_DECREF(SpamError);
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
```

```python
import spam_errors

spam_errors.call(0)   # 84
spam_errors.call(1)   # raises spam_errors.SpamError
```

**Critical rule:** Only the function that detects the error should call `PyErr_SetString()` (or related `PyErr_*` setters). All other functions in the call chain should return `NULL` or `-1` to propagate the error upward. The Python interpreter's main loop eventually handles the exception.

When returning an error, clean up any owned references you created (`Py_DECREF` / `Py_XDECREF`) before returning `NULL`.

### 1.3 Reference Counting

**Full source:** [c_ext_reference_counting](https://github.com/shan-weiqiang/python/tree/main/c_ext_reference_counting) — [`refcount_demo.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_reference_counting/refcount_demo.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_reference_counting/setup.py), [`test_refcount_demo.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_reference_counting/test_refcount_demo.py)

CPython uses reference counting for memory management. Extension authors must manually balance increments and decrements — conceptually similar to C++ `shared_ptr`, but without automatic cleanup.

**Reference counting macros:**

- `Py_INCREF(obj)` — increment (unsafe if `obj` is `NULL`)
- `Py_DECREF(obj)` — decrement; deallocate when count reaches zero (unsafe if `obj` is `NULL`)
- `Py_XINCREF(obj)` — increment (null-safe; the `X` prefix means "do nothing if NULL")
- `Py_XDECREF(obj)` — decrement (null-safe)
- `Py_CLEAR(obj)` — decrement and set the pointer to `NULL` (safest cleanup for struct members)

**Owned vs borrowed references:**

- **Owned reference**: You are responsible for eventually calling `Py_DECREF`.
- **Borrowed reference**: A pointer you did not increment; do not decref it. Valid only as long as the owner keeps the object alive.

**Reference stealing:**

Some APIs take ownership of your reference — you must **not** decref afterward:

```c
/* PyModule_AddObject steals reference to obj */
PyObject *marker = PyUnicode_FromString("owned_by_module");
if (PyModule_AddObject(m, "marker", marker) < 0) {
    Py_DECREF(marker);
    Py_DECREF(m);
    return NULL;
}
```

`PyList_SetItem` also steals; `PyList_Append` does **not** — you must decref after append:

```c
if (PyList_Append(list, value) < 0)
    return NULL;
Py_DECREF(value);  /* PyList_Append does not steal */
```

**Reference returning:**

```c
static PyObject *
demo_new_reference(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *obj = PyList_New(0);            /* new reference — caller owns it */
    if (obj == NULL)
        return NULL;
    return obj;
}

static PyObject *
demo_borrowed_reference(PyObject *self, PyObject *args)
{
    PyObject *list;
    if (!PyArg_ParseTuple(args, "O", &list))
        return NULL;
    PyObject *item = PyList_GetItem(list, 0); /* borrowed — do not decref */
    return PyLong_FromLong(PyLong_AsLong(item));
}
```

See [Reference Counting in C](https://docs.python.org/3/extending/extending.html#reference-counts) for the full rules.

### 1.4 Module Initialization

**Full source:** [c_ext_spam_system](https://github.com/shan-weiqiang/python/tree/main/c_ext_spam_system) (basic module); custom exceptions in [c_ext_exception_propagation](https://github.com/shan-weiqiang/python/tree/main/c_ext_exception_propagation)

Modern Python 3 modules use `PyModuleDef` and a `PyInit_<name>` entry point. The complete `spam` module is shown in §1.1 (`PyMethodDef` table + `PyInit_spam`). After `import spam`, Python calls `PyInit_spam()`, which registers the method table and returns the module object. Each exported function follows the `PyObject *func(PyObject *self, PyObject *args)` convention described above.

Custom exception types are registered the same way (`spam_errors` module):

```c
SpamError = PyErr_NewException("spam_errors.SpamError", NULL, NULL);
Py_INCREF(SpamError);
PyModule_AddObject(m, "SpamError", SpamError);  /* steals SpamError ref */
```

---

## Section 2: Binding Complex C Structures (Refactored)

When a C library exposes structs, arrays, or nested configuration objects, you need a strategy to pass them through Python. Two common approaches are **capsules** (opaque handles) and **custom `PyTypeObject`** instances (full Python types with attribute access).

### 2.1 Approach 1: Opaque Capsule (Simple)

**Full source:** [c_ext_capsule_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_capsule_config) — [`mymodule.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_capsule_config/mymodule.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_capsule_config/setup.py), [`test_mymodule.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_capsule_config/test_mymodule.py)

A capsule wraps a C pointer in an opaque Python object. Python can pass it between C functions but cannot inspect or modify fields directly.

**C struct definition:**

```c
#include <stdbool.h>

struct ComplexConfig {
    int timeout;
    char *server_url;
    bool enable_ssl;
    void *internal_data;
};

int process_config(struct ComplexConfig *config)
{
    int result = config->timeout;
    if (config->enable_ssl)
        result += 100;
    if (config->server_url != NULL && config->server_url[0] != '\0')
        result += (int)strlen(config->server_url);
    return result;
}
```

**Capsule implementation:**

```c
static void
destroy_config(PyObject *capsule)
{
    struct ComplexConfig *config =
        PyCapsule_GetPointer(capsule, "ComplexConfig");
    if (config) {
        free(config->server_url);
        free(config);
    }
}

static PyObject *
py_create_config(PyObject *self, PyObject *args)
{
    int timeout;
    const char *url;
    int ssl;

    if (!PyArg_ParseTuple(args, "isi", &timeout, &url, &ssl))
        return NULL;

    struct ComplexConfig *config = malloc(sizeof(struct ComplexConfig));
    if (!config) {
        PyErr_NoMemory();
        return NULL;
    }
    config->timeout = timeout;
    config->server_url = strdup(url);
    if (!config->server_url) {
        free(config);
        PyErr_NoMemory();
        return NULL;
    }
    config->enable_ssl = (bool)ssl;
    config->internal_data = NULL;

    return PyCapsule_New(config, "ComplexConfig", destroy_config);
}

static PyObject *
py_process_config(PyObject *self, PyObject *args)
{
    PyObject *capsule;

    if (!PyArg_ParseTuple(args, "O", &capsule))
        return NULL;

    if (!PyCapsule_CheckExact(capsule)) {
        PyErr_SetString(PyExc_TypeError, "Expected Config capsule");
        return NULL;
    }

    struct ComplexConfig *config =
        PyCapsule_GetPointer(capsule, "ComplexConfig");
    if (!config) {
        PyErr_SetString(PyExc_ValueError, "Invalid config capsule");
        return NULL;
    }

    int result = process_config(config);
    return PyLong_FromLong(result);
}
```

**Python usage:**

```python
import mymodule

config = mymodule.create_config(30, "http://server.com", True)
result = mymodule.process_config(config)  # 147
# Cannot access: config.timeout, config.server_url
# The capsule is opaque — pass it only to C functions
```

**Pros:** Simple; works for any C struct; no type boilerplate.

**Cons:** No attribute access from Python; harder to debug; no `isinstance` checks.

### 2.2 Approach 2: Custom PyTypeObject (Standard)

This approach creates a full Python type with attribute access, mirroring the C struct. Every such type follows the same `*Object` / `*Type` pattern (§2.2.1). The examples below progress from a basic struct to nested members and arrays.

#### 2.2.1 The `*Object` / `*Type` Pairing

Every Python class in a C extension is defined by two C symbols:

| C symbol | What it is | Python equivalent |
|---|---|---|
| `ConfigObject` | Struct layout of one **instance** | one `Config(...)` object |
| `ConfigType` | Static **`PyTypeObject`** (the class) | `mymodule.Config` |
| `NetworkConfigObject` | Struct layout of one **instance** (nested example in §2.2.3) | one `NetworkConfig(...)` object |
| `NetworkConfigType` | Static **`PyTypeObject`** (the class) | `mymodule.NetworkConfig` |

**Instance (`*Object`):**

- Starts with `PyObject_HEAD`, which expands to `ob_refcnt` and `ob_type`.
- Holds the **per-instance data** (fields you define after the header).
- Created at runtime by `type->tp_alloc()` inside `tp_new`.

**Type (`*Type`):**

- A **single global** `PyTypeObject` struct (not allocated per instance).
- Describes **behavior**: `tp_new`, `tp_init`, `tp_dealloc`, `tp_getset`, `tp_methods`, `tp_basicsize`, etc.
- Registered with `PyType_Ready()` and exposed on the module (e.g. `PyModule_AddObject(m, "Config", ...)`).

**How they connect:**

```c
ConfigObject *cfg = ...;
cfg->ob_type == &ConfigType;   /* every instance points to its class */

NetworkConfigObject *net = ...;
net->ob_type == &NetworkConfigType;
```

In Python, `isinstance(cfg, mymodule.Config)` checks that `cfg->ob_type` is `&ConfigType`. A `ConfigObject` can store a `NetworkConfigObject *` as a member; the nested object still carries its **own** `ob_type` pointing to `&NetworkConfigType`.

![ConfigObject and NetworkConfigObject instances linked to their PyTypeObject types](/assets/images/python_c_ext_object_type_pairing.png)

#### 2.2.2 Basic Example: Simple Struct with Primitive Fields

**Full source:** [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) — [`mymodule.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/mymodule.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/setup.py), [`test_mymodule.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/test_mymodule.py)

**Python object struct:**

```c
typedef struct {
    PyObject_HEAD
    int timeout;
    PyObject *server_url;  /* Python str object */
    bool enable_ssl;
} ConfigObject;
```

**Type methods and slots:**

```c
static void
Config_dealloc(ConfigObject *self)
{
    Py_XDECREF(self->server_url);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
Config_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    ConfigObject *self = (ConfigObject *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->timeout = 0;
        self->server_url = NULL;
        self->enable_ssl = false;
    }
    return (PyObject *)self;
}

static int
Config_init(ConfigObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"timeout", "url", "ssl", NULL};
    int timeout = 0;
    PyObject *url = NULL;
    int ssl = 0;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|iOi", kwlist,
                                     &timeout, &url, &ssl))
        return -1;

    self->timeout = timeout;
    self->enable_ssl = (bool)ssl;
    if (url) {
        Py_INCREF(url);
        Py_XDECREF(self->server_url);
        self->server_url = url;
    }
    return 0;
}

static PyObject *
Config_get_timeout(ConfigObject *self, void *closure)
{
    return PyLong_FromLong(self->timeout);
}

static int
Config_set_timeout(ConfigObject *self, PyObject *value, void *closure)
{
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "timeout must be int");
        return -1;
    }
    self->timeout = (int)PyLong_AsLong(value);
    return 0;
}

static PyObject *
Config_get_server_url(ConfigObject *self, void *closure)
{
    if (self->server_url == NULL)
        return PyUnicode_FromString("");
    Py_INCREF(self->server_url);
    return self->server_url;
}

static int
Config_set_server_url(ConfigObject *self, PyObject *value, void *closure)
{
    if (!PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "server_url must be str");
        return -1;
    }
    Py_INCREF(value);
    Py_XDECREF(self->server_url);
    self->server_url = value;
    return 0;
}

static PyObject *
Config_get_enable_ssl(ConfigObject *self, void *closure)
{
    return PyBool_FromLong(self->enable_ssl);
}

static int
Config_set_enable_ssl(ConfigObject *self, PyObject *value, void *closure)
{
    if (!PyBool_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "enable_ssl must be bool");
        return -1;
    }
    self->enable_ssl = (value == Py_True);
    return 0;
}

static PyGetSetDef Config_getsetters[] = {
    {"timeout", (getter)Config_get_timeout, (setter)Config_set_timeout,
     "timeout in seconds", NULL},
    {"server_url", (getter)Config_get_server_url, (setter)Config_set_server_url,
     "server URL", NULL},
    {"enable_ssl", (getter)Config_get_enable_ssl, (setter)Config_set_enable_ssl,
     "enable SSL", NULL},
    {NULL}
};

static PyObject *
Config_process(ConfigObject *self, PyObject *Py_UNUSED(ignored))
{
    int result = self->timeout * 2;
    return PyLong_FromLong(result);
}

static PyMethodDef Config_methods[] = {
    {"process", (PyCFunction)Config_process, METH_NOARGS, "Process config"},
    {NULL}
};

static PyTypeObject ConfigType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mymodule.Config",
    .tp_doc = "Configuration object",
    .tp_basicsize = sizeof(ConfigObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = Config_new,
    .tp_init = (initproc)Config_init,
    .tp_dealloc = (destructor)Config_dealloc,
    .tp_getset = Config_getsetters,
    .tp_methods = Config_methods,
};
```

**Module initialization** (register the type):

```c
static struct PyModuleDef mymodule_def = {
    PyModuleDef_HEAD_INIT,
    "mymodule",
    "Basic Config type demo.",
    -1,
    NULL
};

PyMODINIT_FUNC
PyInit_mymodule(void)
{
    PyObject *m = PyModule_Create(&mymodule_def);
    if (m == NULL)
        return NULL;

    if (PyType_Ready(&ConfigType) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    Py_INCREF(&ConfigType);
    if (PyModule_AddObject(m, "Config", (PyObject *)&ConfigType) < 0) {
        Py_DECREF(&ConfigType);
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
```

Note: `PyModule_AddObject()` steals the reference to `ConfigType`, so you `Py_INCREF` before adding it.

**Python usage:**

```python
import mymodule

config = mymodule.Config(timeout=30, url="http://server.com", ssl=True)
print(config.timeout)       # 30
config.timeout = 60           # setter works
print(config.server_url)      # http://server.com
result = config.process()     # 120
isinstance(config, mymodule.Config)  # True
```

**Pros:** Full Python integration, attribute access, type checking.

**Cons:** Requires boilerplate (~100 lines for a simple type). [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) generates the same `PyTypeObject` machinery from C++ with far less code ([`c_ext_pybind11_config`](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config)).

#### 2.2.3 Advanced Example: Nested Structs and Arrays

**Full source:** [c_ext_config_nested](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_nested) — [`mymodule.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_nested/mymodule.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_nested/setup.py), [`test_mymodule.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_nested/test_mymodule.py)

This example extends §2.2.2 with a **nested extension type**, a **fixed C array**, and a **`PyObject *` holding a Python `list`**.

**Step 1: Define the nested type (`NetworkConfigObject` + `NetworkConfigType`)**

```c
typedef struct {
    PyObject_HEAD
    char *host;
    int port;
    bool use_ssl;
} NetworkConfigObject;

static PyTypeObject NetworkConfigType;

static void
Network_dealloc(NetworkConfigObject *self)
{
    free(self->host);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
Network_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    NetworkConfigObject *self =
        (NetworkConfigObject *)type->tp_alloc(type, 0);
    if (self) {
        self->host = NULL;
        self->port = 0;
        self->use_ssl = false;
    }
    return (PyObject *)self;
}

static int
Network_init(NetworkConfigObject *self, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"host", "port", "use_ssl", NULL};
    const char *host = NULL;
    int port = 0;
    int use_ssl = 0;

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|sii", kwlist,
                                     &host, &port, &use_ssl))
        return -1;

    if (host) {
        free(self->host);
        self->host = strdup(host);
        if (!self->host) {
            PyErr_NoMemory();
            return -1;
        }
    }
    self->port = port;
    self->use_ssl = (bool)use_ssl;
    return 0;
}

static PyObject *
Network_get_host(NetworkConfigObject *self, void *closure)
{
    if (self->host == NULL)
        return PyUnicode_FromString("");
    return PyUnicode_FromString(self->host);
}

static int
Network_set_host(NetworkConfigObject *self, PyObject *value, void *closure)
{
    if (!PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "host must be str");
        return -1;
    }
    const char *host = PyUnicode_AsUTF8(value);
    free(self->host);
    self->host = strdup(host);
    if (self->host == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    return 0;
}

static PyObject *
Network_get_port(NetworkConfigObject *self, void *closure)
{
    return PyLong_FromLong(self->port);
}

static int
Network_set_port(NetworkConfigObject *self, PyObject *value, void *closure)
{
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "port must be int");
        return -1;
    }
    self->port = (int)PyLong_AsLong(value);
    return 0;
}

static PyObject *
Network_get_use_ssl(NetworkConfigObject *self, void *closure)
{
    return PyBool_FromLong(self->use_ssl);
}

static int
Network_set_use_ssl(NetworkConfigObject *self, PyObject *value, void *closure)
{
    if (!PyBool_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "use_ssl must be bool");
        return -1;
    }
    self->use_ssl = (value == Py_True);
    return 0;
}

static PyGetSetDef Network_getsetters[] = {
    {"host", (getter)Network_get_host, (setter)Network_set_host, "host", NULL},
    {"port", (getter)Network_get_port, (setter)Network_set_port, "port", NULL},
    {"use_ssl", (getter)Network_get_use_ssl, (setter)Network_set_use_ssl,
     "use_ssl", NULL},
    {NULL}
};

static PyTypeObject NetworkConfigType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mymodule.NetworkConfig",
    .tp_basicsize = sizeof(NetworkConfigObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = Network_new,
    .tp_init = (initproc)Network_init,
    .tp_dealloc = (destructor)Network_dealloc,
    .tp_getset = Network_getsetters,
};
```

`NetworkConfigType` is the class; `Network_new` allocates a `NetworkConfigObject` whose `ob_type` will point to `&NetworkConfigType` after `tp_alloc`.

**Step 2: Define the main instance struct (`ConfigObject`)**

```c
typedef struct {
    PyObject_HEAD
    int timeout;
    PyObject *server_url;
    bool enable_ssl;
    NetworkConfigObject *network;   /* nested extension instance */
    int values[10];                 /* fixed C array */
    int values_count;               /* number of used slots in values[] */
    PyObject *items;                /* Python list (PyObject *) */
} ConfigObject;
```

- **`values[]` / `values_count`**: pure C storage; expose to Python via methods.
- **`items`**: an owned reference to a Python `list`; expose via a property getter/setter.
- **`network`**: pointer to another extension instance (`NetworkConfigObject *`).

**Step 3: Nested member — getter/setter**

```c
static PyObject *
Config_get_network(ConfigObject *self, void *closure)
{
    if (self->network == NULL) {
        /* tp_new initializes host/port/use_ssl — do not use PyObject_New */
        self->network = (NetworkConfigObject *)
            NetworkConfigType.tp_new(&NetworkConfigType, NULL, NULL);
        if (self->network == NULL)
            return NULL;
    }
    Py_INCREF(self->network);
    return (PyObject *)self->network;
}

static int
Config_set_network(ConfigObject *self, PyObject *value, void *closure)
{
    if (!PyObject_TypeCheck(value, &NetworkConfigType)) {
        PyErr_SetString(PyExc_TypeError, "network must be NetworkConfig");
        return -1;
    }
    Py_INCREF(value);
    Py_XDECREF(self->network);
    self->network = (NetworkConfigObject *)value;
    return 0;
}
```

`PyObject_TypeCheck(value, &NetworkConfigType)` verifies the nested value is an instance of the nested **type** object.

**Step 4: Fixed array and list members**

Fixed C array — expose through methods:

```c
static PyObject *
Config_get_value(ConfigObject *self, PyObject *args)
{
    int index;
    if (!PyArg_ParseTuple(args, "i", &index))
        return NULL;
    if (index < 0 || index >= self->values_count) {
        PyErr_SetString(PyExc_IndexError, "index out of range");
        return NULL;
    }
    return PyLong_FromLong(self->values[index]);
}

static PyObject *
Config_set_value(ConfigObject *self, PyObject *args)
{
    int index;
    PyObject *value;
    if (!PyArg_ParseTuple(args, "iO", &index, &value))
        return NULL;
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "value must be int");
        return NULL;
    }
    if (index < 0 || index >= 10) {
        PyErr_SetString(PyExc_IndexError, "index out of range");
        return NULL;
    }
    self->values[index] = (int)PyLong_AsLong(value);
    if (index >= self->values_count)
        self->values_count = index + 1;
    Py_RETURN_NONE;
}

static PyObject *
Config_get_values(ConfigObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *list = PyList_New(self->values_count);
    if (list == NULL)
        return NULL;
    for (int i = 0; i < self->values_count; i++)
        PyList_SET_ITEM(list, i, PyLong_FromLong(self->values[i]));
    return list;
}
```

Python list member — store a `PyObject *` directly:

```c
static PyObject *
Config_get_items(ConfigObject *self, void *closure)
{
    if (self->items == NULL)
        return PyList_New(0);
    Py_INCREF(self->items);
    return self->items;
}

static int
Config_set_items(ConfigObject *self, PyObject *value, void *closure)
{
    if (!PyList_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "items must be a list");
        return -1;
    }
    Py_INCREF(value);
    Py_XDECREF(self->items);
    self->items = value;
    return 0;
}
```

**Step 5: Complete type (`ConfigType`) and module init**

Destructor, constructor, tables, and the **`ConfigType`** definition (reuse `Config_init` and primitive getters/setters from §2.2.2):

```c
static void
Config_dealloc(ConfigObject *self)
{
    Py_XDECREF(self->server_url);
    Py_XDECREF(self->network);
    Py_XDECREF(self->items);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
Config_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    ConfigObject *self = (ConfigObject *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->timeout = 0;
        self->server_url = NULL;
        self->enable_ssl = false;
        self->network = NULL;
        self->values_count = 0;
        self->items = NULL;
        /* tp_alloc zero-fills memory, so values[] starts at {0, ...} */
    }
    return (PyObject *)self;
}

static PyGetSetDef Config_getsetters[] = {
    {"timeout", (getter)Config_get_timeout, (setter)Config_set_timeout,
     "timeout in seconds", NULL},
    {"server_url", (getter)Config_get_server_url, (setter)Config_set_server_url,
     "server URL", NULL},
    {"enable_ssl", (getter)Config_get_enable_ssl, (setter)Config_set_enable_ssl,
     "enable SSL", NULL},
    {"network", (getter)Config_get_network, (setter)Config_set_network,
     "network settings", NULL},
    {"items", (getter)Config_get_items, (setter)Config_set_items,
     "items list", NULL},
    {NULL}
};

static PyMethodDef Config_methods[] = {
    {"get_value", (PyCFunction)Config_get_value, METH_VARARGS, "Get value by index"},
    {"set_value", (PyCFunction)Config_set_value, METH_VARARGS, "Set value by index"},
    {"get_values", (PyCFunction)Config_get_values, METH_NOARGS, "Get all values"},
    {NULL}
};

static PyTypeObject ConfigType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mymodule.Config",
    .tp_doc = "Configuration object with nested struct and arrays",
    .tp_basicsize = sizeof(ConfigObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = Config_new,
    .tp_init = (initproc)Config_init,
    .tp_dealloc = (destructor)Config_dealloc,
    .tp_getset = Config_getsetters,
    .tp_methods = Config_methods,
};
```

Register **`NetworkConfigType` before `ConfigType`**:

```c
static struct PyModuleDef mymodule_def = {
    PyModuleDef_HEAD_INIT,
    "mymodule",
    "Nested Config type demo.",
    -1,
    NULL
};

PyMODINIT_FUNC
PyInit_mymodule(void)
{
    PyObject *m = PyModule_Create(&mymodule_def);
    if (m == NULL)
        return NULL;

    if (PyType_Ready(&NetworkConfigType) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    Py_INCREF(&NetworkConfigType);
    if (PyModule_AddObject(m, "NetworkConfig",
                           (PyObject *)&NetworkConfigType) < 0) {
        Py_DECREF(m);
        return NULL;
    }

    if (PyType_Ready(&ConfigType) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    Py_INCREF(&ConfigType);
    if (PyModule_AddObject(m, "Config", (PyObject *)&ConfigType) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
```

**Python usage:**

```python
import mymodule

config = mymodule.Config(timeout=30)
config.network.host = "server.com"
config.network.port = 8080
config.network.use_ssl = True

isinstance(config, mymodule.Config)                    # True
isinstance(config.network, mymodule.NetworkConfig)     # True

net = mymodule.NetworkConfig(host="standalone.com", port=9000)
config.network = net

config.set_value(0, 10)
config.set_value(1, 20)
values = config.get_values()   # [10, 20]

config.items = [1, 2, 3, 4, 5]
items = config.items           # [1, 2, 3, 4, 5]
```

### 2.3 Summary: Opaque Capsule vs Full Python Type

The two binding approaches differ in how much of the C struct is visible to Python, not in whether C code can run at all. Both can call existing C functions directly from extension methods.

**Opaque capsule (Approach 1)**

- Wrap a plain C struct pointer in `PyCapsule_New`; Python sees an opaque handle.
- When a method needs to process the object, extract the pointer with `PyCapsule_GetPointer` and pass it straight to existing C APIs — no field-by-field conversion.
- Minimal boilerplate; ideal when Python only needs to *create*, *pass*, and *destroy* handles, not inspect or mutate fields.
- Downside: no `config.timeout` in Python, no `isinstance` checks against a meaningful type, harder debugging in a REPL.

**Full Python type mirror (Approach 2)**

- The `*Object` struct **is** the binding: instance data lives in C fields (and owned `PyObject *` members), exposed through getters/setters and methods.
- Methods still run as **C functions** — `Config_process(self, args)` reads `self->timeout` and can call any existing C library routine. You do **not** need to reimplement processing logic in Python.
- Conversion is only required when the **layout differs**. If your library already uses `struct ComplexConfig` and your `ConfigObject` stores different types (e.g. `PyObject *` for strings instead of `char *`), you either:
  - design `ConfigObject` to match what the C API expects and call C directly, or
  - write a small **marshal/unmarshal** layer (Python mirror → stack/local C struct → call C function) at method boundaries.

  That marshalling cost is paid at call sites, not by rewriting the library in Python.

**Sketch: marshal at the method boundary**

**Full source:** [c_ext_config_marshal](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_marshal) — [`mymodule.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_marshal/mymodule.c), [`setup.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_marshal/setup.py), [`test_mymodule.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_marshal/test_mymodule.py)

Suppose the existing C library owns this layout and API:

```c
/* Existing C library — unchanged */
struct ComplexConfig {
    int timeout;
    char *server_url;
    bool enable_ssl;
};

int process_config(const struct ComplexConfig *config)
{
    int result = config->timeout;
    if (config->enable_ssl)
        result += 1000;
    if (config->server_url != NULL)
        result += (int)strlen(config->server_url);
    return result;
}
```

Your Python-facing type stores Python objects instead (different layout):

```c
typedef struct {
    PyObject_HEAD
    int timeout;
    PyObject *server_url;   /* Python str, not char * */
    bool enable_ssl;
} ConfigObject;
```

Build a stack-local C struct inside the method, call the library, then clean up:

```c
/* Copy mirror fields → plain C struct (marshal) */
static int
config_to_c(ConfigObject *self, struct ComplexConfig *out)
{
    out->timeout = self->timeout;
    out->enable_ssl = self->enable_ssl;

    if (self->server_url == NULL) {
        out->server_url = NULL;
        return 0;
    }
    if (!PyUnicode_Check(self->server_url)) {
        PyErr_SetString(PyExc_TypeError, "server_url must be str");
        return -1;
    }
    out->server_url = strdup(PyUnicode_AsUTF8(self->server_url));
    if (out->server_url == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    return 0;
}

static void
config_c_free(struct ComplexConfig *cfg)
{
    free(cfg->server_url);
    cfg->server_url = NULL;
}

static PyObject *
Config_process(ConfigObject *self, PyObject *Py_UNUSED(ignored))
{
    struct ComplexConfig cfg;

    if (config_to_c(self, &cfg) < 0)
        return NULL;

    int result = process_config(&cfg);   /* existing C code, unchanged */
    config_c_free(&cfg);
    return PyLong_FromLong(result);
}
```

```python
import mymodule

config = mymodule.Config(timeout=30, url="http://server.com", ssl=True)
config.process()  # 1047
```

The pattern: **`ConfigObject` holds Python-friendly data**; **methods marshal → call C → cleanup**. Attribute access never touches `struct ComplexConfig`; only methods that call the legacy API pay conversion cost.

**Shared rules regardless of approach**

- Every full type needs an `*Object` / `*Type` pair; nested types register before types that depend on them.
- Owned `PyObject *` members require `Py_XDECREF` in the destructor; getters return borrowed or new references consistently.
- C processing logic stays in C in both approaches — the choice is how much structure you expose to Python, not whether you abandon C for business logic.

---

## References

- [Extending Python with C or C++](https://docs.python.org/3/extending/extending.html): Official tutorial covering extension functions, exceptions, reference counting, and module initialization.
- [Build a C Extension Module for Python – Real Python](https://realpython.com/build-python-c-extension-module/): Practical walkthrough of building, compiling, and testing a C extension module.
- [Python Internals: How Callables Work (PyCoder's Weekly CN)](https://pycoders-weekly-chinese.readthedocs.io/en/latest/issue6/python-internals-how-callables-work.html): Explains `CALL_FUNCTION`, `PyObject_Call`, `tp_call`, and CEval fast paths for `PyCFunction` and `PyFunction`.
- [Defining Extension Types](https://docs.python.org/3/extending/newtypes.html): Official guide to creating custom `PyTypeObject` instances with attributes and methods.
- [Reference Counting in C](https://docs.python.org/3/extending/extending.html#reference-counts): Rules for owned, borrowed, and stolen references in extension code.
- [C API — Reference Management](https://docs.python.org/3/c-api/refcounting.html): Complete reference for `Py_INCREF`, `Py_DECREF`, and related macros.
- [Parsing arguments and building values](https://docs.python.org/3/c-api/arg.html): Format strings for `PyArg_ParseTuple`, `PyArg_ParseTupleAndKeywords`, and `Py_BuildValue`.
- [Python Data Model — Code objects](https://docs.python.org/3/reference/datamodel.html#code-objects): Structure and role of `PyCodeObject` in the execution model.
- [dis — Disassembler](https://docs.python.org/3/library/dis.html): Tool for inspecting bytecode generated from Python source.
- [Part VII — pybind11](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-pybind11.html) — pybind11 reimplementation of §2.2.2 `Config` ([c_ext_pybind11_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_pybind11_config))
- [Part VIII — Extensions vs Bindings](https://shan-weiqiang.github.io/2026/06/21/python-c-extension-concepts.html)

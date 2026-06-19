---
layout: post
title:  "Python C Extensions: Overview"
date:   2026-06-19 9:22:46 +0800
tags: [python]
---

* toc
{:toc}

This overview walks through how Python C extensions work from the ground up: writing extension functions, binding C data structures to Python, the interpreter's general execution model, how pure Python bytecode runs, how C extension methods dispatch to native code, and how the two paths compare end to end. The six sections build on each other; read them in order for the complete picture. More focused articles on specific C extension topics will follow.

## Section 1: Python C Extension Fundamentals

### 1.1 Basic C Extension Function Structure

A minimal extension function wraps a C library call and exposes it to Python. The canonical example from the official documentation wraps `system()`:

```c
#define PY_SSIZE_T_CLEAN
#include <Python.h>

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

**Error propagation pattern** (illustrative):

```c
// Layer 3: deepest function — sets the specific error
static PyObject *
layer3_func(PyObject *args)
{
    if (some_check_fails) {
        PyErr_SetString(SpamError, "Specific error: file not found");
        return NULL;
    }
    return result;
}

// Layer 2: middle function — just propagates
static PyObject *
layer2_func(PyObject *args)
{
    PyObject *obj = layer3_func(args);
    if (obj == NULL)
        return NULL;  /* Don't call PyErr_* — layer 3 already set it */
    return process(obj);
}

// Layer 1: top function — just propagates
static PyObject *
layer1_func(PyObject *args)
{
    PyObject *result = layer2_func(args);
    if (result == NULL)
        return NULL;
    return result;
}
```

**Critical rule:** Only the function that detects the error should call `PyErr_SetString()` (or related `PyErr_*` setters). All other functions in the call chain should return `NULL` or `-1` to propagate the error upward. The Python interpreter's main loop eventually handles the exception.

When returning an error, clean up any owned references you created (`Py_DECREF` / `Py_XDECREF`) before returning `NULL`.

### 1.3 Reference Counting

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
PyModule_AddObject(module, "name", obj);  /* steals reference to obj */
PyList_SetItem(list, 0, obj);             /* steals reference to obj */
```

**Reference returning:**

Some functions return a new reference (you own it); others return a borrowed reference:

```c
PyObject *obj = PyList_New(0);            /* new reference — you must decref */
PyObject *item = PyList_GetItem(list, 0); /* borrowed — do not decref */
```

See [Reference Counting in C](https://docs.python.org/3/extending/extending.html#reference-counts) for the full rules.

### 1.4 Module Initialization

Modern Python 3 modules use `PyModuleDef` and a `PyInit_<name>` entry point:

```c
static PyMethodDef SpamMethods[] = {
    {"system", spam_system, METH_VARARGS, "Execute a shell command."},
    {NULL, NULL, 0, NULL}  /* sentinel */
};

static struct PyModuleDef spammodule = {
    PyModuleDef_HEAD_INIT,
    "spam",           /* module name */
    "Spam module.",   /* module docstring */
    -1,               /* per-module state size (-1 = no state) */
    SpamMethods
};

PyMODINIT_FUNC
PyInit_spam(void)
{
    return PyModule_Create(&spammodule);
}
```

After `import spam`, Python calls `PyInit_spam()`, which registers the method table and returns the module object. Each exported function follows the `PyObject *func(PyObject *self, PyObject *args)` convention described above.

---

## Section 2: Binding Complex C Structures (Refactored)

When a C library exposes structs, arrays, or nested configuration objects, you need a strategy to pass them through Python. Two common approaches are **capsules** (opaque handles) and **custom `PyTypeObject`** instances (full Python types with attribute access).

### 2.1 Approach 1: Opaque Capsule (Simple)

A capsule wraps a C pointer in an opaque Python object. Python can pass it between C functions but cannot inspect or modify fields directly.

**C struct definition:**

```c
struct ComplexConfig {
    int timeout;
    char *server_url;
    bool enable_ssl;
    void *internal_data;
};

int process_config(struct ComplexConfig *config);
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
    config->enable_ssl = (bool)ssl;

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
result = mymodule.process_config(config)
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

**Python object struct:**

```c
typedef struct {
    PyObject_HEAD
    int timeout;
    PyObject *server_url;  /* Python str object */
    bool enable_ssl;
} ConfigObject;
```

**Type methods and slots** (abbreviated; see [Defining Extension Types](https://docs.python.org/3/extending/newtypes.html) for the full pattern):

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

**Cons:** Requires boilerplate (~100 lines for a simple type).

#### 2.2.3 Advanced Example: Nested Structs and Arrays

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

    if (host)
        self->host = strdup(host);
    self->port = port;
    self->use_ssl = (bool)use_ssl;
    return 0;
}

/* ... getters/setters for host, port, use_ssl ... */

static PyTypeObject NetworkConfigType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mymodule.NetworkConfig",
    .tp_basicsize = sizeof(NetworkConfigObject),
    .tp_new = Network_new,
    .tp_init = (initproc)Network_init,
    .tp_dealloc = (destructor)Network_dealloc,
    /* .tp_getset = Network_getsetters, */
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
        self->network = (NetworkConfigObject *)
            PyObject_New(NetworkConfigObject, &NetworkConfigType);
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

Suppose the existing C library owns this layout and API:

```c
/* Existing C library — unchanged */
struct ComplexConfig {
    int timeout;
    char *server_url;   /* owned by caller or library convention */
    bool enable_ssl;
};

int process_config(const struct ComplexConfig *config);
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

The pattern: **`ConfigObject` holds Python-friendly data**; **methods marshal → call C → cleanup**. Attribute access never touches `struct ComplexConfig`; only methods that call the legacy API pay conversion cost.

**Shared rules regardless of approach**

- Every full type needs an `*Object` / `*Type` pair; nested types register before types that depend on them.
- Owned `PyObject *` members require `Py_XDECREF` in the destructor; getters return borrowed or new references consistently.
- C processing logic stays in C in both approaches — the choice is how much structure you expose to Python, not whether you abandon C for business logic.

---

## Section 3: General Python Interpreter Execution Model

Before comparing Python classes and C extensions, it helps to see the **shared machinery** both paths use. CPython runs programs in two phases: compile Python source to bytecode, then execute bytecode in an interpreter loop. Every callable — Python function, C function, bound method, or type object — is ultimately invoked through the same **`tp_call`** dispatch on `ob_type`.

> **Note:** Opcode names, frame layout, and internal function names vary by Python version (especially 3.11+). The model below is conceptual; use [`dis`](https://docs.python.org/3/library/dis.html) on your target version for exact bytecode.

### 3.1 Two-Phase Execution: Compile, Then Interpret

```
Python source  →  compiler  →  code objects (bytecode + constants + names)
                                    ↓
                             eval loop (PyEval_EvalFrameEx / _PyEval_EvalFrame)
                                    ↓
                             PyObject results, exceptions, or returns
```

- **Compile time:** functions, class bodies, and module top-level code become `PyCodeObject` instances.
- **Run time:** the eval loop reads opcodes from a **frame**, operates on an operand **stack**, and calls C API helpers (`PyObject_Call`, `PyObject_SetAttr`, etc.).

  A **frame** is the runtime context for one active function call — bytecode, locals, instruction pointer, and that call's stack. The eval loop fetches the next opcode from the frame, executes it, and repeats.

  The **operand stack** is an internal stack of `PyObject *` values. Opcodes such as `LOAD_FAST` push locals onto it; `STORE_ATTR` pops from it. For `self.timeout = timeout`, the stack might go `[timeout]` → `[timeout, self]` → `[]`.

  Bytecode instructions are tiny; the real work is done by **C API helpers**. The eval loop dispatches opcodes to well-defined C routines rather than reimplementing Python semantics in raw pointer manipulation:

  | Opcode (examples) | C API helper (conceptually) |
  |---|---|
  | `STORE_ATTR` | `PyObject_SetAttr(obj, name, value)` |
  | `CALL` | `PyObject_Call(...)` or a fast path (§3.5) |
  | `BINARY_OP` / multiply | `PyNumber_Multiply(left, right)` |

C extension code runs **inside** this loop when Python calls into it; it bypasses the loop only when the callable's `tp_call` goes directly to native code (e.g. `PyCFunction_Call`).

### 3.2 Everything Is an Object: `PyObject` and `ob_type`

```c
typedef struct _object {
    PyObject_HEAD   /* ob_refcnt + ob_type pointer */
} PyObject;
```

Every value — `int`, `list`, function, module, type — is a `PyObject`. The **`ob_type`** pointer identifies what the object is and which operations apply:

```c
PyTypeObject *type = Py_TYPE(obj);
type->tp_call;      /* how to call it */
type->tp_getattro;  /* attribute lookup */
type->tp_dealloc;   /* destruction */
/* ... dozens of slots ... */
```

Python's runtime is a **tagged union**: behavior is selected by `ob_type`, not by inspecting raw memory.

### 3.3 Universal Call Dispatch: `PyObject_Call` and `tp_call`

All calls converge here (simplified from `Objects/call.c`):

```c
PyObject *
PyObject_Call(PyObject *callable, PyObject *args, PyObject *kwds)
{
    ternaryfunc call = callable->ob_type->tp_call;
    if (call != NULL)
        return call(callable, args, kwds);
    PyErr_Format(PyExc_TypeError, "'%.200s' object is not callable",
                 callable->ob_type->tp_name);
    return NULL;
}
```

Each callable type registers its own `tp_call`:

| Callable type | `tp_call` implementation | What runs |
|---|---|---|
| `PyFunctionObject` | `PyFunction_Call` | Build frame → **bytecode eval loop** |
| `PyCFunctionObject` | `PyCFunction_Call` | **Direct C function pointer** |
| `PyTypeObject` (class) | `type_call` | `tp_new` + `tp_init` |
| User object with `__call__` | `slot_tp_call` | Looks up `__call__`, then recurses |

Section 4 traces the **Python function** branch; Section 5 traces the **C function** branch.

### 3.4 The Eval Loop: Frames, Stack, and Opcodes

When `tp_call` leads to a `PyFunctionObject`, CPython builds a **frame** and runs its bytecode:

```c
/* Conceptual eval loop — not complete CPython source */
PyObject *
PyEval_EvalFrame(PyFrameObject *frame)
{
    unsigned char *bytecode = PyBytes_AS_STRING(frame->f_code->co_code);
    PyObject **stack = frame->f_valuestack;
    PyObject **locals = frame->f_localsplus;
    PyObject *obj, *value, *left, *right, *name, *result;

    for (;;) {
        unsigned char opcode = *bytecode++;
        unsigned char oparg = *bytecode++;

        switch (opcode) {
        case LOAD_FAST:
            /* stack: [...] → [..., locals[oparg]] */
            PUSH(locals[oparg]);
            break;

        case LOAD_CONST:
            /* stack: [...] → [..., co_consts[oparg]] */
            PUSH(PyTuple_GET_ITEM(frame->f_code->co_consts, oparg));
            break;

        case STORE_ATTR:
            /* self.timeout = timeout
             * stack: [timeout, self] → [] */
            value = POP();
            obj = POP();
            name = PyTuple_GET_ITEM(frame->f_code->co_names, oparg);
            PyObject_SetAttr(obj, name, value);  /* C API helper */
            Py_DECREF(obj);
            Py_DECREF(value);
            break;

        case BINARY_OP:  /* or BINARY_MULTIPLY in older bytecode */
            /* self.timeout * 2
             * stack: [2, timeout] → [result] */
            right = POP();
            left = POP();
            result = PyNumber_Multiply(left, right);  /* C API helper */
            Py_DECREF(left);
            Py_DECREF(right);
            PUSH(result);
            break;

        case CALL:
            /* stack: [..., arg1, callable] → [..., result] */
            result = call_function(...);  /* → PyObject_Call or fast path (§3.5) */
            PUSH(result);
            break;

        case RETURN_VALUE:
            return POP();
        /* ... hundreds of other opcodes ... */
        }
    }
}
```

Each `case` is thin: **decode opcode → shuffle stack → call a C API helper**. `STORE_ATTR` delegates to `PyObject_SetAttr`; multiplication delegates to `PyNumber_Multiply`; calls delegate to `call_function` / `PyObject_Call`.

Key ideas:

- **Frame** — binds a `PyCodeObject` to locals, stack depth, and instruction pointer.
- **Stack machine** — most opcodes push/pop `PyObject *` references.
- **Per-opcode cost** — dispatch, refcounting, and dynamic checks; far more expensive than a single C statement.

### 3.5 The `CALL` Opcode: `call_function` and Fast Paths

This section is about what happens when the eval loop executes the **`CALL` bytecode instruction** — not every way Python can invoke a callable. Calls made directly from C extension code via `PyObject_Call()` or `PyObject_CallObject()` skip the eval loop entirely; they go straight to `tp_call`. Here we focus on calls that originate **inside** running bytecode.

When bytecode runs `obj.process()`, the eval loop hits **`CALL`**. Arguments and the callable already sit on the **operand stack** as individual `PyObject *` values — not yet packed into a tuple or dict.

#### Generic (slow) path: pack, then `PyObject_Call`

The fully general route (`do_call` in `ceval.c`) does extra work:

1. Pop positional arguments off the stack into a new **`PyTuple`**.
2. Pop keyword arguments into a new **`PyDict`**.
3. Call **`PyObject_Call(callable, tuple, dict)`** → `callable->ob_type->tp_call(...)`.
4. Inside `tp_call`, the callee often **unpacks** that tuple again.

This is correct for any callable, but allocating and filling tuple/dict on every call is expensive when the common cases are plain Python functions and C functions with positional args only.

#### Fast path: recognize the type, skip packing

A **fast path** is an optimization inside **`call_function()`** (`Python/ceval.c`) that handles frequent cases **before** building tuple/dict. It still ends up running the same `tp_call` logic (or equivalent), but avoids the packing step.

The check is explicit type identification — the same `ob_type` tag from §3.2:

```c
/* Simplified from ceval.c — not complete source */
static PyObject *
call_function(PyThreadState *tstate, PyObject ***pp_stack, int oparg)
{
    int na = PyVectorcall_NARGS(oparg);   /* positional arg count */
    int nk = oparg >> 8;                  /* keyword arg count */
    PyObject **stack = *pp_stack;
    PyObject *callable = stack[-na - nk - 1];

    /* --- Fast path 1: C function, no keyword arguments --- */
    if (PyCFunction_Check(callable) && nk == 0) {
        PyCFunctionObject *cf = (PyCFunctionObject *)callable;
        PyCFunction meth = cf->m_ml->ml_meth;
        /* Call meth(self, ...) using values still on the stack */
        return /* direct invoke based on METH_* flags */;
    }

    /* --- Fast path 2: Python function --- */
    if (PyFunction_Check(callable)) {
        return fast_function(tstate, pp_stack, oparg, na, nk);
        /* Builds a frame; keeps args on stack where possible */
    }

    /* --- Slow path: arbitrary callable --- */
    return do_call(callable, stack, na, nk);
    /* Builds tuple + dict → PyObject_Call → tp_call */
}
```

**How the interpreter decides:**

| Step | What is checked | Meaning |
|---|---|---|
| 1 | `PyCFunction_Check(callable)` | `Py_TYPE(callable) == &PyCFunction_Type`? |
| 2 | `nk == 0` | No keyword arguments on this `CALL`? |
| 3 | `METH_*` flags | C API allows this arg layout (e.g. `METH_NOARGS`, `METH_VARARGS`)? |
| 4 | else `PyFunction_Check(callable)` | `Py_TYPE(callable) == &PyFunction_Type`? → `fast_function()` |
| 5 | else | Fall back to `do_call` → `PyObject_Call` |

`PyCFunction_Check` and `PyFunction_Check` are **pointer comparisons** on `ob_type`, not introspection of Python source code.

**Concrete example:** `math.sqrt(9)` from bytecode

```
CALL 1          # one positional arg, zero keywords
```

1. Stack (bottom → top): `[..., sqrt, 9]`
2. `call_function` sees `callable = sqrt`, `na = 1`, `nk = 0`.
3. `PyCFunction_Check(sqrt)` is true → fast path.
4. Reads `sqrt`'s `ml_meth` pointer, calls it with `9` — **no tuple allocated**, no `PyObject_Call` wrapper.
5. Result pushed back on the stack.

**Concrete example:** `f(x, y)` for a Python `def`

1. `PyFunction_Check(f)` is true → `fast_function()` builds an execution frame wired to `f->func_code` and runs `PyEval_EvalFrame`.
2. Still no generic `PyObject_Call` + tuple round-trip when the fast path applies.

**Concrete example:** `obj(key=value)` or a custom `__call__`

1. `nk > 0` or callable is neither `PyCFunction` nor `PyFunction` → **slow path**.
2. `do_call` packs stack values into tuple/dict, then `PyObject_Call` → that type's `tp_call` (e.g. `slot_tp_call` for a class instance).

![CALL opcode dispatch through call_function fast and slow paths](/assets/images/python_c_ext_call_opcode_flow.png)

**Takeaway:** Python and C extension calls both start as the same `CALL` opcode. They diverge inside `call_function()` when **`ob_type` is inspected**. Fast paths are not a different calling convention — they are shortcuts to the same `tp_call` implementations (`PyCFunction_Call`, `PyFunction_Call`) that skip tuple/dict allocation when the stack layout already matches what those functions need.

`PyObject_Call` does not always create a frame. It only invokes `callable->ob_type->tp_call`:

```
PyObject_Call(callable, args, kwds)
  → tp_call(callable, args, kwds)
       → PyFunction_Call  → new frame → PyEval_EvalFrame   (bytecode)
       → PyCFunction_Call → ml_meth(...) in C               (no frame)
```

Whether a **new eval frame** appears depends on the callable type, not on fast vs slow path:

| Path | `PyObject_Call`? | New frame? | Runs bytecode? |
|---|---|---|---|
| C fast path (`PyCFunction_Check`, `nk == 0`) | usually skipped | **no** | **no** — native C |
| Python fast path (`PyFunction_Check` → `fast_function`) | skipped | **yes** | **yes** |
| Slow path → C (`do_call` → `PyCFunction_Call`) | yes | no | no |
| Slow path → Python (`do_call` → `PyFunction_Call`) | yes | yes | yes |

**C extension call from bytecode:**

```
CALL → call_function (C fast path) → Config_process(self, args) → result on stack
```

No `PyObject_Call`, no new frame — there is no bytecode for the C method.

**Python function call from bytecode:**

```
CALL → fast_function → new frame → PyEval_EvalFrame
        (slow path: do_call → PyObject_Call → PyFunction_Call → same destination)
```

Fast path for Python functions saves tuple/dict packing; it does **not** skip bytecode execution.

Calls made **directly from C extension code** via `PyObject_Call()` never hit the `CALL` opcode at all — they go straight to `tp_call` with no eval-loop involvement.

---

## Section 4: Pure Python Bytecode Execution

Pure Python classes and functions store logic as **bytecode** inside `PyFunctionObject`. Section 3 showed the generic eval loop; this section shows what Python-specific structures are built and how a class method reaches that loop.

### 4.1 Compilation: Source to Bytecode

When Python encounters a class or function definition, it compiles the body into a code object:

```python
class Config:
    def __init__(self, timeout):
        self.timeout = timeout

    def process(self):
        return self.timeout * 2
```

Inspect the bytecode for `__init__`:

```python
import dis
dis.dis(Config.__init__)
```

Typical output (Python 3.12):

```
  2           0 RESUME                   0

  3           2 LOAD_FAST                1 (timeout)
              4 LOAD_FAST                0 (self)
              6 STORE_ATTR               0 (timeout)
              ...
```

**Code object structure** (conceptual; see [Code objects](https://docs.python.org/3/reference/datamodel.html#code-objects)):

```c
typedef struct {
    PyObject_HEAD
    int co_argcount;
    int co_flags;
    PyObject *co_code;      /* bytecode bytes */
    PyObject *co_consts;    /* constants tuple */
    PyObject *co_names;     /* names used */
    PyObject *co_varnames;  /* local variable names */
    int co_stacksize;
    /* ... */
} PyCodeObject;
```

A **function object** wraps a code object with defaults and globals:

```c
typedef struct {
    PyObject_HEAD
    PyCodeObject *func_code;
    PyObject *func_globals;
    PyObject *func_defaults;
    /* ... */
} PyFunctionObject;
```

### 4.2 Class Creation via Bytecode Execution

The `class` statement itself compiles to bytecode:

```python
dis.dis("class Config:\n    def __init__(self, timeout):\n        self.timeout = timeout")
```

Typical sequence:

```
  0 LOAD_BUILD_CLASS
  2 LOAD_CONST               0 (<code object Config>)
  4 LOAD_CONST               1 ('Config')
  6 MAKE_FUNCTION
  8 LOAD_CONST               1 ('Config')
 10 CALL_FUNCTION            2
 12 STORE_NAME               0 (Config)
 14 RETURN_CONST             1 (None)
```

**Execution steps:**

1. `LOAD_BUILD_CLASS` — push `__build_class__` onto the stack.
2. `LOAD_CONST` / `MAKE_FUNCTION` — wrap the class body in a `PyFunctionObject`.
3. `CALL_FUNCTION` — call `__build_class__(func, "Config", ...)` (Section 3 eval loop).
4. `STORE_NAME` — bind the resulting `PyTypeObject` to `Config`.

### 4.3 How `__build_class__` Creates a PyTypeObject

Simplified illustration (not verbatim CPython source):

```c
PyObject *
__build_class__(PyObject *func, PyObject *name, ...)
{
    PyObject *namespace = PyDict_New();
    PyObject_Call(func, ...);
    /* namespace: "__init__", "process", ... as PyFunctionObjects */

    PyTypeObject *new_type = (PyTypeObject *)
        type_new(&PyType_Type, name, bases, namespace);

    if (PyDict_GetItemString(namespace, "__init__"))
        new_type->tp_init = slot_tp_init;
    if (PyDict_GetItemString(namespace, "__repr__"))
        new_type->tp_repr = slot_tp_repr;

    new_type->tp_dict = namespace;
    PyType_Ready(new_type);
    return (PyObject *)new_type;
}
```

The class body runs as ordinary bytecode. Each `def` creates a `PyFunctionObject` in the namespace dictionary.

### 4.4 Generic Slot Wrappers

CPython provides **shared generic wrappers** for Python-defined classes. `__init__` in source does not become `tp_init` directly — it becomes a `PyFunctionObject` in `tp_dict`, and `tp_init` points to `slot_tp_init`:

```c
static int
slot_tp_init(PyObject *self, PyObject *args, PyObject *kwds)
{
    PyObject *meth = lookup_special_method(self, "__init__");
    if (meth == NULL)
        return 0;

    PyObject *full_args = /* tuple with self prepended */;
    PyObject *res = PyObject_Call(meth, full_args, kwds);
    /* validate res is None, cleanup, return */
}
```

The wrapper calls `PyObject_Call` on the Python `__init__` function → `PyFunction_Call` → **bytecode eval loop** (Section 3.4).

### 4.5 Python Method Execution Path

For `obj.process()` on a pure Python class (Section 6 compares this path side by side with the C extension path):

```
obj.process()
  → PyObject_GetAttr(obj, "process")       # tp_dict → PyFunctionObject
  → bound method or function lookup
  → CALL opcode → PyObject_Call / fast_function
  → PyFunction_Type.tp_call → PyFunction_Call
  → PyEval_EvalFrame                       # Section 3.4
  → per-opcode dispatch until RETURN_VALUE
```

**Example: `self.timeout = timeout` in `__init__`:**

```
LOAD_FAST   1 (timeout)
LOAD_FAST   0 (self)
STORE_ATTR  0 (timeout)
```

Stack: push `timeout`, push `self`, then `STORE_ATTR` calls `PyObject_SetAttr(self, "timeout", timeout)`.

Each opcode pays interpreter dispatch, stack manipulation, refcounting, and dynamic checks — far more than a direct C field write.

### 4.6 Complete Execution Flow for a Python Class

![Complete execution flow for defining and using a pure Python class](/assets/images/python_c_ext_python_class_flow.png)

---

## Section 5: C Extension Execution

C extension types and module functions store logic as **C function pointers**, not bytecode. Section 3 showed that all calls go through `tp_call`; this section traces the C extension path from `PyMethodDef` to direct native execution.

### 5.1 Method Definition and Registration

```c
static PyMethodDef Config_methods[] = {
    {"process", (PyCFunction)Config_process, METH_NOARGS, "Process config"},
    {"get_value", (PyCFunction)Config_get_value, METH_VARARGS, "Get value by index"},
    {NULL, NULL, 0, NULL}
};

static PyTypeObject ConfigType = {
    /* ... */
    .tp_methods = Config_methods,
};
```

**`PyMethodDef` structure:**

```c
typedef struct PyMethodDef {
    const char  *ml_name;
    PyCFunction  ml_meth;   /* C function pointer — not bytecode */
    int          ml_flags;
    const char  *ml_doc;
} PyMethodDef;
```

| Flag | C signature |
|---|---|
| `METH_NOARGS` | `PyObject *func(PyObject *self)` |
| `METH_O` | `PyObject *func(PyObject *self, PyObject *arg)` |
| `METH_VARARGS` | `PyObject *func(PyObject *self, PyObject *args)` |
| `METH_KEYWORDS` | `PyObject *func(PyObject *self, PyObject *args, PyObject *kwargs)` |

### 5.2 `PyType_Ready()` Creates Method Descriptors

At import time, `PyType_Ready()` converts each `PyMethodDef` into a **`PyMethodDescrObject`** in `tp_dict`:

```c
int
PyType_Ready(PyTypeObject *type)
{
    if (type->tp_dict == NULL)
        type->tp_dict = PyDict_New();

    if (type->tp_methods != NULL) {
        for (PyMethodDef *meth = type->tp_methods; meth->ml_name != NULL; meth++) {
            PyObject *descr = PyDescr_NewMethod(type, meth);
            PyDict_SetItemString(type->tp_dict, meth->ml_name, descr);
            Py_DECREF(descr);
        }
    }
    return 0;
}
```

The C pointer lives in the descriptor's embedded `PyMethodDef`, not in a `PyCodeObject`.

### 5.3 Attribute Lookup: From `tp_dict` Descriptor to Bound `PyCFunctionObject`

**At import time** (`PyType_Ready`), the type's dictionary holds **unbound method descriptors** — not callables you can invoke directly without an instance:

```
ConfigType->tp_dict = {
    "process": PyMethodDescrObject {
        ob_type = &PyMethodDescr_Type,
        d_type  = &ConfigType,              /* owner type */
        d_name  = "process",
        d_method = &Config_methods[0],       /* PyMethodDef { ml_meth = Config_process } */
    },
    "get_value": PyMethodDescrObject { ... },
}
```

The C pointer (`Config_process`) lives inside the descriptor's `PyMethodDef`. Nothing is bound to a particular `config` instance yet.

**At runtime**, `config.process` runs **attribute lookup** on the instance:

```python
config = mymodule.Config()
config.process   # step 1: lookup only — returns a bound callable
config.process() # step 2: CALL on that callable (§3.5, §5.4)
```

**Step-by-step** (simplified from `Objects/object.c` and descriptor code):

```
config.process
  │
  ├─ 1. PyObject_GetAttr(config, "process")
  │      type = Py_TYPE(config)  →  &ConfigType
  │
  ├─ 2. PyDict_GetItem(type->tp_dict, "process")
  │      → PyMethodDescrObject  (found on the class, not on the instance)
  │
  ├─ 3. Descriptor protocol: method descriptors are "non-data" descriptors
  │      When accessed on an instance, call descr->ob_type->tp_descr_get(descr, config, ConfigType)
  │      → PyMethodDescr_Get(...)
  │
  └─ 4. PyMethodDescr_Get builds a fresh PyCFunctionObject:
         m_ml   = same PyMethodDef * as in the descriptor  (still Config_process)
         m_self = config                                       ← "binding"
         ob_type = &PyCFunction_Type
```

**What "bound" means:** the descriptor is shared by all `Config` instances (one entry in `tp_dict`). Binding copies the **`PyMethodDef` pointer** into a new **`PyCFunctionObject`** and sets **`m_self = config`** so `Config_process` receives the correct instance as its first argument.

```
Before (in tp_dict, shared by all instances):
  PyMethodDescrObject  →  PyMethodDef { ml_meth = Config_process }
                          (no instance attached)

After config.process (per lookup, a new wrapper object):
  PyCFunctionObject {
      ob_type = &PyCFunction_Type,
      m_ml    = PyMethodDef { ml_meth = Config_process, ml_flags = METH_NOARGS },
      m_self  = <ConfigObject * for this config>,
  }
```

**Why two object types?**

| Object | Lives where | Role |
|---|---|---|
| `PyMethodDescrObject` | `ConfigType->tp_dict["process"]` | Template: name + C pointer + owner type |
| `PyCFunctionObject` | Created on each `config.process` access | Callable: C pointer + **bound** `self` |

`ConfigType.process` (access on the **class**) would bind differently (`m_self = NULL` or the class object); `config.process` (on an **instance**) sets `m_self` to that instance.

**Lookup on `config.process()`** (the call, not the lookup):

```
LOAD_ATTR / attribute load  →  PyObject_GetAttr  →  bound PyCFunctionObject  (above)
CALL opcode                 →  call_function / PyCFunction_Call
                            →  meth = m_ml->ml_meth;  meth(m_self, args)
                            →  Config_process(config, NULL)
```

So the chain in §5.7 is:

```
PyMethodDef.ml_meth
  → PyType_Ready → PyMethodDescrObject in tp_dict["process"]
  → config.process → PyObject_GetAttr → tp_descr_get → PyCFunctionObject (m_self=config)
  → config.process() → CALL → PyCFunction_Call → Config_process
```

### 5.4 Call Dispatch: `PyCFunction_Call`

When `config.process()` runs, the `CALL` opcode reaches `PyCFunction_Type.tp_call`:

```c
PyObject *
PyCFunction_Call(PyObject *func_obj, PyObject *args, PyObject *kwds)
{
    PyCFunctionObject *func = (PyCFunctionObject *)func_obj;
    PyCFunction meth = func->m_ml->ml_meth;
    PyObject *self = func->m_self;
    int flags = func->m_ml->ml_flags;

    if (flags & METH_NOARGS) {
        return meth(self, NULL);
    }
    else if (flags & METH_VARARGS) {
        return meth(self, args);
    }
    /* ... METH_KEYWORDS, etc. ... */
}
```

This is a **direct C call** — no `PyEval_EvalFrame`, no bytecode. The eval loop's `call_function()` fast path can invoke `meth` even without going through `PyObject_Call` when kwargs are absent.

### 5.5 C Extension Slots and Built-in Types

Special methods can bypass Python entirely. A C type sets **`tp_as_sequence->sq_length`** directly:

```c
static Py_ssize_t
Config_len(ConfigObject *self)
{
    return self->size;
}

static PySequenceMethods Config_as_sequence = {
    .sq_length = (lenfunc)Config_len,
};
```

Built-in `list`, `dict`, `str`, etc. use the same model — native slots and `tp_methods`, all registered on `PyTypeObject` at startup.

### 5.6 Type Tags: How the Interpreter "Knows"

```c
#define PyCFunction_Check(op) Py_IS_TYPE(op, &PyCFunction_Type)
#define PyFunction_Check(op)  Py_IS_TYPE(op, &PyFunction_Type)
```

`ob_type` is the identity card. `PyCFunction_Type.tp_call` runs C code; `PyFunction_Type.tp_call` runs bytecode. Section 3's `PyObject_Call` and `call_function()` branch on these tags.

### 5.7 Summary: C Extension Execution Path

Section 6 places this chain next to the pure Python path from §4.5.

```
PyMethodDef.ml_meth  (C pointer at definition)
        ↓
PyType_Ready → PyMethodDescrObject in tp_dict["process"]
        ↓
config.process → PyObject_GetAttr → tp_descr_get → PyCFunctionObject (m_self = config)
        ↓
config.process() → CALL → PyCFunction_Call → meth(m_self, args)
        ↓
Native machine code (Config_process)
```

No bytecode is ever compiled for `Config_process`. The only interpreter involvement is reaching the call site and marshalling arguments.

---

## Section 6: Execution Path Comparison — Pure Python vs C Extension

Sections 4 and 5 traced each path in isolation. This section lines them up for the same operation — **`instance.process()`** — so you can see where they match and where they diverge.

Both paths assume bytecode is already running (for example inside a script that calls `obj.process()` or `config.process()`). Section 3 established that all callables are `PyObject *` values dispatched through `ob_type->tp_call`; Section 6 shows what sits behind that dispatch for each kind of method.

### 6.1 Shared Steps Up to the `CALL` Opcode

For either a pure Python class or a C extension type, the call site looks the same from the eval loop's perspective:

```
instance.process()
  → LOAD_ATTR (or equivalent) → PyObject_GetAttr(instance, "process")
  → operand stack holds a bound callable
  → CALL opcode → call_function()                    # §3.5
```

Attribute lookup always consults the instance's type (`instance->ob_type->tp_dict`). The **type of object** returned from lookup is where the two paths split.

### 6.2 Pure Python Method Path (§4.5)

For `obj.process()` on a class defined in Python:

```
obj.process()
  → PyObject_GetAttr(obj, "process")       # tp_dict → PyFunctionObject
  → bound method or function lookup
  → CALL opcode → PyObject_Call / fast_function
  → PyFunction_Type.tp_call → PyFunction_Call
  → PyEval_EvalFrame                       # §3.4
  → per-opcode dispatch until RETURN_VALUE
```

**What is stored at definition time:** a `PyFunctionObject` whose `func_code` points to a `PyCodeObject` (bytecode produced when the class body ran — §4.2–§4.4).

**What binding produces:** a `PyMethodObject` (or similar bound callable) that pairs the function with `obj` as `self`.

**What execution does:** enters a **new frame** and runs the bytecode instruction loop — `LOAD_FAST`, `STORE_ATTR`, `CALL`, and so on — until `RETURN_VALUE`. Every statement in the method pays interpreter overhead.

### 6.3 C Extension Method Path (§5.7)

For `config.process()` on a type defined in C:

```
PyMethodDef.ml_meth  (C pointer at definition)
        ↓
PyType_Ready → PyMethodDescrObject in tp_dict["process"]
        ↓
config.process → PyObject_GetAttr → tp_descr_get → PyCFunctionObject (m_self = config)
        ↓
config.process() → CALL → PyCFunction_Call → meth(m_self, args)
        ↓
Native machine code (Config_process)
```

**What is stored at definition time:** a `PyMethodDef` row with `ml_meth = Config_process` — a **C function pointer**, not bytecode (§5.1).

**What binding produces:** a `PyCFunctionObject` with `m_self = config` and the same `PyMethodDef *` (§5.3).

**What execution does:** `PyCFunction_Call` reads `ml_meth` and `m_self`, then **jumps directly into C** (§5.4). No `PyCodeObject`, no `PyEval_EvalFrame`, no opcode loop inside the method body.

### 6.4 Stage-by-Stage Comparison

| Stage | Pure Python (`obj.process()`) | C extension (`config.process()`) |
|---|---|---|
| **Method definition** | `def process(self): ...` compiled to `PyCodeObject` | `PyMethodDef` + C function `Config_process` |
| **In `tp_dict`** | `PyFunctionObject` (unbound function) | `PyMethodDescrObject` (wraps `PyMethodDef`) |
| **`instance.process` lookup** | Function descriptor → bound `PyMethodObject` | Method descriptor → `PyCFunctionObject` (`m_self = instance`) |
| **Callable `ob_type`** | `&PyFunction_Type` | `&PyCFunction_Type` |
| **`CALL` fast path** | `fast_function()` → new frame, args on stack | Direct `meth(self, ...)` from stack (§3.5) |
| **`tp_call` handler** | `PyFunction_Call` → `PyEval_EvalFrame` | `PyCFunction_Call` → C function pointer |
| **Method body runs as** | Bytecode opcodes in a nested frame | Native machine instructions |
| **Interpreter loop after call returns** | Resumes in caller's frame | Resumes in caller's frame (same) |

The last row matters: once `process()` returns, both paths land back in the **caller's** bytecode frame. Only the **callee** differs — nested eval loop vs direct native execution.

### 6.5 Side-by-Side at the Divergence Point

After `PyObject_GetAttr`, the eval loop has a callable on the stack. From there:

```
Pure Python                          C extension
────────────────────────────────     ────────────────────────────────
PyFunctionObject                     PyCFunctionObject
  func_code → PyCodeObject             m_ml → PyMethodDef { ml_meth }
  (bytecode)                           m_self → ConfigObject *

CALL → PyFunction_Type.tp_call       CALL → PyCFunction_Type.tp_call
     → PyFunction_Call                    → PyCFunction_Call
     → PyEval_EvalFrame                   → Config_process(config, NULL)
     → LOAD_FAST / STORE_ATTR / ...       → (direct field access, no opcodes)
     → RETURN_VALUE
```

For a one-line method like `self.timeout = timeout`, the Python path executes multiple opcodes and dynamic attribute machinery (§4.5). The C extension path can assign `self->timeout` in a single native store inside `Config_init` or `Config_process` — no nested frame.

### 6.6 Unified Diagram

![Execution path comparison: pure Python class method vs C extension method](/assets/images/python_c_ext_execution_path_comparison.png)

The diagram shows the fork after `PyObject_GetAttr`: Python methods re-enter the eval loop; C extension methods exit to native code. Both paths converge again when the method returns and the caller's `CALL` completes.

### 6.7 Takeaway

| Question | Pure Python | C extension |
|---|---|---|
| Is there bytecode for the method? | Yes (`PyCodeObject`) | No |
| Does `process()` start a new eval frame? | Yes | No |
| Where does the "real work" run? | Opcode loop (§3.4) | C function pointer (§5.4) |
| Why use C extensions for hot paths? | — | Skip frame setup and per-opcode dispatch |

The interpreter does not treat `obj.process()` and `config.process()` as different bytecode instructions — both are `LOAD_ATTR` followed by `CALL`. The performance gap comes from **what the callable is**: a `PyFunctionObject` that spawns another bytecode interpreter pass, or a `PyCFunctionObject` that hands control to machine code after a thin wrapper.

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

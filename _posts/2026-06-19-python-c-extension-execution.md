---
layout: post
title:  "Python C Extensions: Part II — PyCFunction Dispatch"
date:   2026-06-19 13:31:46 +0800
tags: [python]
---

* toc
{:toc}

This article covers how CPython executes code: the shared interpreter model, pure Python bytecode, C extension method dispatch, and a side-by-side comparison of the two paths. It continues from [Part I — Overview](https://shan-weiqiang.github.io/2026/06/19/python-c-extension-overview.html) (Sections 1–2). [Part III — ctypes and CFFI](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-cffi.html) covers calling plain C libraries without hand-writing `PyInit_*` for each library. [Part IV — Complex ctypes Structs and Handles](https://shan-weiqiang.github.io/2026/06/19/python-c-ctypes-complex-structs.html) covers ctypes struct handles (fd, capsule, `Structure`) and user API above them.

Runnable demos for the Python examples below live in the [python](https://github.com/shan-weiqiang/python) repository.

| Section | Demo folder |
|---|---|
| §4.1 | [c_ext_exec_python_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_python_config) |
| §4.2 | [c_ext_exec_class_bytecode](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_class_bytecode) |
| §5.1, §5.3 | [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic), [c_ext_config_nested](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_nested) |
| §6.5 | [c_ext_exec_compare](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_compare) |

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

**Full source:** [c_ext_exec_python_config](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_python_config) — [`config.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_python_config/config.py), [`test_config.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_python_config/test_config.py)

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

Output on Python 3.12:

```
  4           0 RESUME                   0

  5           2 LOAD_FAST                1 (timeout)
              4 LOAD_FAST                0 (self)
              6 STORE_ATTR               0 (timeout)
             16 RETURN_CONST             0 (None)
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

**Full source:** [c_ext_exec_class_bytecode](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_class_bytecode) — [`test_class_bytecode.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_class_bytecode/test_class_bytecode.py)

The `class` statement itself compiles to bytecode:

```python
import dis
dis.dis("class Config:\n    def __init__(self, timeout):\n        self.timeout = timeout")
```

Output on Python 3.12:

```
  0           0 RESUME                   0

  1           2 PUSH_NULL
              4 LOAD_BUILD_CLASS
              6 LOAD_CONST               0 (<code object Config ...>)
              8 MAKE_FUNCTION            0
             10 LOAD_CONST               1 ('Config')
             12 CALL                     2
             20 STORE_NAME               0 (Config)
             22 RETURN_CONST             2 (None)
```

**Execution steps:**

1. `LOAD_BUILD_CLASS` — push `__build_class__` onto the stack.
2. `LOAD_CONST` / `MAKE_FUNCTION` — wrap the class body in a `PyFunctionObject`.
3. `CALL` — call `__build_class__(func, "Config", ...)` (Section 3 eval loop).
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

**Full source:** [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) (`Config.process`, §5.3–§5.7), [c_ext_config_nested](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_nested) (`get_value` / `set_value` / `get_values`, §5.1)

C extension types and module functions store logic as **C function pointers**, not bytecode. Section 3 showed that all calls go through `tp_call`; this section traces the C extension path from `PyMethodDef` to direct native execution.

### 5.1 Method Definition and Registration

**Full source:** [`mymodule.c` (nested Config)](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_nested/mymodule.c), [`mymodule.c` (basic Config)](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/mymodule.c)

From the nested `Config` type:

```c
static PyMethodDef Config_methods[] = {
    {"get_value", (PyCFunction)Config_get_value, METH_VARARGS, "Get value by index"},
    {"set_value", (PyCFunction)Config_set_value, METH_VARARGS, "Set value by index"},
    {"get_values", (PyCFunction)Config_get_values, METH_NOARGS, "Get all values"},
    {NULL}
};

static PyTypeObject ConfigType = {
    /* ... */
    .tp_methods = Config_methods,
};
```

The basic `Config` type in §2.2.2 of the overview article registers `process` with `METH_NOARGS` the same way.

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

**Full source:** [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic) — [`mymodule.c`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/mymodule.c), [`test_mymodule.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_config_basic/test_mymodule.py)

```python
import mymodule

config = mymodule.Config(timeout=30)
bound = config.process   # step 1: lookup — returns a bound PyCFunctionObject
result = config.process()  # step 2: CALL → Config_process(config, NULL) → 60
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

**Full source:** [c_ext_exec_compare](https://github.com/shan-weiqiang/python/tree/main/c_ext_exec_compare) — [`py_config.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_compare/py_config.py), [`test_compare.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_compare/test_compare.py); C extension side uses [c_ext_config_basic](https://github.com/shan-weiqiang/python/tree/main/c_ext_config_basic)

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

Runnable check:

**Full source:** [`test_compare.py`](https://github.com/shan-weiqiang/python/blob/main/c_ext_exec_compare/test_compare.py)

```python
import mymodule  # c_ext_config_basic

class PyConfig:
    def __init__(self, timeout):
        self.timeout = timeout

    def process(self):
        return self.timeout * 2

py_cfg = PyConfig(30)
c_cfg = mymodule.Config(timeout=30)
assert py_cfg.process() == c_cfg.process() == 60

# Python: bound method has __code__ (bytecode)
assert hasattr(PyConfig.process, "__code__") or hasattr(py_cfg.process, "__code__")

# C extension: bound method is builtin_function_or_method — no bytecode
assert str(type(c_cfg.process)) == "<class 'builtin_function_or_method'>"
assert not hasattr(c_cfg.process, "__code__")
```

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

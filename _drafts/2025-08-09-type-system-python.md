---
layout: post
title:  "Type systems: Part IV Python"
date:   2025-08-09 9:22:46 +0800
tags: [programming]
---

Previously:
- [Type systems: Part I](https://shan-weiqiang.github.io/2024/07/14/understanding-types.html)
- [Type systems: Part II Protobuf Reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html)

Now:

```c
typedef struct _object {
_PyObject_HEAD_EXTRA
Py_ssize_t ob_refcnt;
struct _typeobject *ob_type;
} PyObject;
```
- `_PyObject_HEAD_EXTRA` macro: pointers that points to previous PyObject and next PyObject
- `ob_refcnt`: reference counter
- `ob_type`: *type* of current PyObject instance

The `PyTypeObject` is the most important type in Python implementation that enables dynamic typing. Type erasure is achieved through this type. See the [C-API for CPython](https://docs.python.org/3/c-api/typeobj.html). The most important thing that this type object contains are *function pointers*, which are responsible for various operations on instances of this type: allocation, deallocation, hash, etc. This is exactly where the type erasure happens: *binding of function pointers during construction and hide detailed operation inside implementation*. Once the binding is finished, an instance, even it's Python variable, it's type is fixed, the functions that used to operate on this instance is fixed, until it's destruction. Even though this Python variable can be bind to another Python instance, might be a different typed instance, but the underlying PyObject's type is fixed. Compare this with `std::function`:

- `std::function` variable can be used to bind to different typed callables, underneath `std::function` keeps different function pointers that implement these callables.
- `std::function` variable can be reassigned to another callable with the same signature, with the previous callable properly deallocated by it's bound deallocators and with new instance + new set of function pointers kept inside the same `std::function`

Python's dynamic typing works very much like `std::function`, using type erasure technique. **A PyTypeObject is itself a PyObject instance at runtime**.

When a new object is created, its ob_type is set to the appropriate PyTypeObject(**binding during construction, as in type erasure**). For example:

A list object has ob_type set to &PyList_Type. An integer object has ob_type set to &PyLong_Type. For custom types, you define a PyTypeObject and set the object's ob_type to point to it.

ob_type is used for type checking functions like isinstance(obj, cls) and issubclass(cls1, cls2). For instance, PyObject_IsInstance(inst, cls) checks if inst->ob_type is cls or if cls is in the base classes of inst->ob_type. This is supported by Python C API: Object Protocol, which lists functions like PyObject_IsInstance and P_IsSubclass, relying on the type hierarchy defined by tp_base and tp_bases in PyTypeObject.

When an operation is performed on an object, Python uses ob_type to find the appropriate function pointers in the PyTypeObject. For example: Calling len() on a list uses list->ob_type->tp_as_sequence->sq_length.

While possible, changing ob_type (e.g., via __class__ assignment) is restricted. From Python C API: Type Objects, it's noted that __class__ assignment is only supported for mutable types or ModuleType subclasses, to prevent crashes or undefined behavior:

```python
# Class definion in Python actually will instantiate a PyTypeObject
# instance in C during runtime. It is also a PyObject instance and
# have the same lifetime management with other Python instances.
# When this type is not used anymore, it is deallocated. When defined
# this type belongs to a module, tmp.py, and it is reference by this
# module.
class MyClass:
    class_var = 10

    def __init__(self, x):
        self.x = x

    def method(self):
        print(f"Original method, class_var={self.class_var}")


# Create an instance using this type. This instance is also
# a PyObject and add one more reference count to MyClass's
# PyTypeObject. The type binding happens here during instance
# construction.
obj = MyClass(5)
obj.method()  # Outputs: Original method, class_var=10


# Redefine the class. This creates a new PyTypeObject instance and
# makes the original MyClass's reference count one less count. Since
# Now tmp.py module has a new MyClass type. But the original MyClass
# is still in memory, because the obj instance still refers to it.
class MyClass:
    class_var = 20

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def method(self):
        print(f"New method, class_var={self.class_var}")


# Check existing instance. obj still use the original MyClass, since
# the binding is not changed.
obj.method()  # Outputs: Original method, class_var=10

# Create a new instance. Now the new MyClass is used, since inside
# module tmp.py, the MyClass now is the new PyTypeObject.
new_obj = MyClass(5, 10)
new_obj.method()  # Outputs: New method, class_var=20


def m(self, sec):
    print("New individual method")


# We can change the class attributes like any other python instance
# Underneath, a type in Python is just a PyTypeObject in C.
MyClass.method = m
# error
# new_obj.method("dummy")
new_obj.method("dummy")

# This is dangerous!! Since it will reduce reference count of the
# orinal MyClass object(class are also runtime PyObject instances)
# to zero, and it will be freed from memory. This will change the
# type of obj, which determines member function poitners,
# destructor pointers, etc, hence create a inconsistency between
#  obj's memory and it's type, since it's memory is created by the
#  original MyClass type.
obj.__class__ = MyClass
print(obj.class_var)

```

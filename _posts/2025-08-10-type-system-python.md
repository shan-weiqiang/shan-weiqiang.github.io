---
layout: post
title:  "Type systems: Part IV Python"
date:   2025-08-10 9:22:46 +0800
tags: [programming]
---

Previously:
- [Type systems: Part I](https://shan-weiqiang.github.io/2024/07/14/understanding-types.html)
- [Type systems: Part II Protobuf Reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html)
- [Type systems: Part III Json](https://shan-weiqiang.github.io/2025/08/10/type-system-json.html)


Now:

# PyTypeObject

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

# Inheritence

The `PyTypeObject` structure contains fields that implement inheritance:

```C
typedef struct _typeobject {
    PyObject_VAR_HEAD
    const char *tp_name;                 /* For printing, in format "<module>.<name>" */
    Py_ssize_t tp_basicsize, tp_itemsize; /* For allocation */
    
    /* Methods to implement standard operations */
    destructor tp_dealloc;
    printfunc tp_print;
    getattrfunc tp_getattr;
    setattrfunc tp_setattr;
    PyAsyncMethods *tp_as_async; /* formerly known as tp_compare (Python 2) or tp_reserved (Python 3) */
    reprfunc tp_repr;
    
    /* Method suites for standard classes */
    PyNumberMethods *tp_as_number;
    PySequenceMethods *tp_as_sequence;
    PyMappingMethods *tp_as_mapping;
    
    /* More standard operations (here for binary compatibility) */
    hashfunc tp_hash;
    ternaryfunc tp_call;
    reprfunc tp_str;
    getattrofunc tp_getattro;
    setattrofunc tp_setattro;
    
    /* Functions to access object as input/output buffer */
    PyBufferProcs *tp_as_buffer;
    
    /* Flags to define presence of optional/expanded features */
    unsigned long tp_flags;
    
    const char *tp_doc; /* Documentation string */
    
    /* call function for all accessible objects */
    traverseproc tp_traverse;
    
    /* delete references to contained objects */
    inquiry tp_clear;
    
    /* rich comparisons */
    richcmpfunc tp_richcompare;
    
    /* weak reference enabler */
    Py_ssize_t tp_weaklistoffset;
    
    /* Iterators */
    getiterfunc tp_iter;
    iternextfunc tp_iternext;
    
    /* Attribute descriptor and subclassing stuff */
    struct PyMethodDef *tp_methods;
    struct PyMemberDef *tp_members;
    struct PyGetSetDef *tp_getset;
    struct _typeobject *tp_base;
    PyObject *tp_dict;
    descrgetfunc tp_descr_get;
    descrsetfunc tp_descr_set;
    Py_ssize_t tp_dictoffset;
    initproc tp_init;
    allocfunc tp_alloc;
    newfunc tp_new;
    freefunc tp_free; /* Low-level free-memory routine */
    inquiry tp_is_gc; /* For PyObject_IS_GC */
    PyObject *tp_bases;
    PyObject *tp_mro; /* method resolution order */
    PyObject *tp_cache;
    PyObject *tp_subclasses;
    PyObject *tp_weaklist;
    destructor tp_del;
    
    /* Type attribute cache version tag. Added in version 2.6 */
    unsigned int tp_version_tag;
    
    destructor tp_finalize;
    
} PyTypeObject;
```
The key fields for inheritance are:
- `tp_base`: Points to the immediate base class(PyTypeObject)
- `tp_bases`: Tuple of all base classes(PyTypeObject)
- `tp_mro`: Method Resolution Order tuple

When you define a class in Python:
```python
class Child(Parent):
    pass
```
The Python runtime:
- Creates a new PyTypeObject for Child
- Sets Child->tp_base to point to Parent's PyTypeObject
- Sets Child->tp_bases to a tuple containing Parent's PyTypeObject
- Computes the MRO (Method Resolution Order) and stores it in Child->tp_mro

Inheritence enable current class *inherit* attributes from it's base classes:

```
Class (PyTypeObject)
    tp_base → Parent Class (PyTypeObject)
    tp_bases → (Parent1, Parent2, ...) (PyTypeObject)
    tp_mro → (Class, Parent1, Parent2, ..., object)
    tp_dict → {attribute_name: attribute_value, ...}
    tp_new, tp_init, tp_dealloc → function pointers
```

# Metaclasses

Metaclasses are also `PyTypeObject` instances. When you define a metaclass:
```python
class Meta(type):
    pass

class MyClass(metaclass=Meta):
    pass
```

The relationship is:
- MyClass.ob_type points to Meta's PyTypeObject
- Meta.ob_type points to type's PyTypeObject (since Meta inherits from type)
- type.ob_type points to itself (since type is its own metaclass)

*metaclass* are classes that inherits from *type*, since *type* is a *PyObject* that can create *PyTypeObject*, which are classes:

```
Instance (PyObject)
    ob_type → Class (PyTypeObject)
        ob_type → Metaclass (PyTypeObject)  
            ob_type → type (PyTypeObject)
                ob_type → type (self-referential)
```

**Every PyObject only have one `ob_type` pointer, hence can only point to one metaclass**:

```python
class Meta1(type):
    pass

class Meta2(type):
    pass

# SyntaxError: keyword argument repeated: metaclass
class MyClass(metaclass=Meta1, metaclass=Meta2):
    pass
```

metaclass support inheritence:

```python
class MetaBase(type):
    def __new__(cls, name, bases, namespace):
        print(f"MetaBase.__new__: {name}")
        namespace['base_attr'] = 'from_meta_base'
        return super().__new__(cls, name, bases, namespace)

class MetaMiddle(MetaBase):
    def __new__(cls, name, bases, namespace):
        print(f"MetaMiddle.__new__: {name}")
        namespace['middle_attr'] = 'from_meta_middle'
        return super().__new__(cls, name, bases, namespace)

class MetaTop(MetaMiddle):
    def __new__(cls, name, bases, namespace):
        print(f"MetaTop.__new__: {name}")
        namespace['top_attr'] = 'from_meta_top'
        return super().__new__(cls, name, bases, namespace)

class MyClass(metaclass=MetaTop):
    pass

# Output:
# MetaBase.__new__: MyClass
# MetaMiddle.__new__: MyClass  
# MetaTop.__new__: MyClass

print(MyClass.base_attr)    # 'from_meta_base'
print(MyClass.middle_attr)  # 'from_meta_middle'
print(MyClass.top_attr)     # 'from_meta_top'
```

At C level:

```
MyClass.ob_type → MetaTop's PyTypeObject
    ob_type → MetaMiddle's PyTypeObject
        ob_type → MetaBase's PyTypeObject
            ob_type → type's PyTypeObject
                ob_type → type's PyTypeObject (self-referential)
```

Both inheritence and metaclass can add attributes to a class, but they work at totally different level:

- Inheritence only *inherit* attributes from it's parents
- Metaclass directly operate on class's attributes, during class *creation*

```python
class Meta(type):
    def __new__(cls, name, bases, namespace):
        print(f"Metaclass executing during class creation")
        namespace['meta_attr'] = 'added by metaclass'
        return super().__new__(cls, name, bases, namespace)

class Base:
    base_attr = 'inherited from base'
    def __init__(self):
        print("Base class executing during instance creation")

# Metaclass executes NOW (during class definition)
class MyClass(Base, metaclass=Meta):
    pass

# Base class attributes are already available
print(MyClass.meta_attr)  # 'added by metaclass'
print(MyClass.base_attr)  # 'inherited from base'
```

Metaclass can directly operate on the *raw namespace* of the class type: `namespace`. Inheritence only inherit attributes from base classes through *inheritence lookup*:

- Metaclass creates class just like anyother PyTypeObject create instances, internally it's type erasure and once instances are created, the binding is fixed, attributes are added permanently on this class.
- Inheritence is just pointers to parent classes, they can be changed dynamically.


# Memory in inheritence

When a class has parents, all parents attributes and the child class attributes are stored in one single dictionary:

```python
class Parent:
    def __init__(self):
        self.a = 1

class Child(Parent):
    def __init__(self):
        super().__init__()
        self.b = 2

c = Child()

```
```
>>> c.__dict__
{'a': 1, 'b': 2}
```

You can’t quite do a true C++-style “object slicing” in Python, because Python doesn’t physically store a separate “Parent object” inside a “Child object.”

In Python:

- `c` is the Child instance.
- The “Parent part” isn’t a separate object — it’s just that Child inherits the methods and attributes of Parent.
- When you call a Parent method on c, Python simply follows the Method Resolution Order (MRO) to find that method in Parent, but still passes the same c object as self.

```python
class Parent:
    def p_method(self):
        print("Parent method, self is:", self)

class Child(Parent):
    def c_method(self):
        print("Child method, self is:", self)

c = Child()
c.p_method()  # Works — no casting needed
```
```
Parent method, self is: <__main__.Child object at 0x10100dbe0>
```


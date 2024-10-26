---
layout: post
title:  "Python descriptors"
date:   2023-04-22 19:22:46 +0800
tags: [python]
---


Python descriptor is the mechanism behind instance method, classmethod, staticmethod, property. Also descriptor plays a key role in attribute lookup order. This article tries to explain descriptor as detailed as possible, hoping to save some time for anyone who are interested in this topic, since I myself spend a lot of time searching over the web about descriptor. However, even though information are there, there is not one place where I can know them all. This article tries to solve this problem.

* toc
{:toc}

# Time saver

Of course, the final interpretation always belongs to official documentation. If you can read and understand following link without difficulties, then do not waste time reading this paper anymore.

[Descriptor HowTo Guide](https://docs.python.org/3/howto/descriptor.html)

# What is descriptor?

Facts about descriptor:

- A class is called descriptor if it implements **one or more** of following methods:
    - `__get__(self, obj, type=None) -> object`
    - `__set__(self, obj, value) -> None`
    - `__delete__(self, obj) -> None`
- For descriptors to work, it has to be class variable of another class
- When descriptor variables are accessed using dotted expression, `__get__` method is called
- When descriptor variables are set using dotted expression, `__set__` method is called
- When descriptor is accessed, the parameters are passed to methods automatically

Nothing says more than examples, here is code example that explains what is descriptor and how it is accessed:

```python
class SomeDescriptor:
    """Descriptor class"""

    def __get__(self, obj, obj_type=None):
        """Called when descriptor is accessed

        Parameters:
            self: descriptor instance
            obj:  instance to which this descriptor instance belongs
            obj_type: instance class type to which this descriptor instance belongs
        """
        return 42

    def __set__(self, obj, value):
        """Called when descriptor is set

        Parameters:
            self: descriptor instance
            obj:  instance to which this descriptor instance belongs
            value: value that about to set
        """
        print("Descriptor is being set")

class SomeClass:
    """Some class that use descriptor"""

    # descriptor has to be class variable to work
    dsp = SomeDescriptor()

ins = SomeClass()
# ins.dsp calls __get__ and return 42
print(ins.dsp)
# ins.dsp set to 6 will call __set__
ins.dsp = 6
```

Output:

```python
42
Descriptor is being set
```

Note that when `__set__` and `__get__` are called, the parameters are passed automatically

## Category of descriptor

- Non-data descriptors: descriptors that only implement `__get__` method
- Data descriptors: descriptors that implement `__set__` or `__delete__` method

Data and non-data descriptors will have influence on attribute lookup order in follow chapters.

## What is the use of `__set_name__` method？

Key information about `__set_name__(self, owner, name)` :

- This method is used to let the descriptor know what name it is assigned to
- It’s called when class is defined  as a callback

Here is an example to show how `__set_name__` works:

```python
class SomeDescriptor:
    """Descriptor class"""

    # This method will be called when class SomeClass is defined
    def __set_name__(self, owner, name):
        """Let self know what variable name it is assigned"""
        self.self_name = name
        print(self.self_name)
        print(owner)

    def __get__(self, obj, obj_type=None):
        """Called when descriptor is accessed

        Parameters:
            self: descriptor instance
            obj:  instance to which this descriptor instance belongs
            obj_type: instance class type to which this descriptor instance belongs
        """
        return 42

    def __set__(self, obj, value):
        """Called when descriptor is set

        Parameters:
            self: descriptor instance
            obj:  instance to which this descriptor instance belongs
            value: value that about to set
        """
        print("Descriptor is being set")

class SomeClass:
    """Some class that use descriptor"""

    # descriptor has to be class variable to work
    dsp = SomeDescriptor()
```

Output:

```python
dsp # The descriptor instance now know that it is assigned name 'dsp'
<class '__main__.SomeClass'>
```

What is interesting about this output is that in our Python code there is no statement, only definitions, which demonstrates that the `__set_name__` method is called when `SomeClass` is *defined*.

# Python attribute lookup order

First of all, everything in Python is `object` . `object` have `attribute` . `attribute` can be accessed by dotted expression, such as `a.b` or by `object.__getattribute__()` method. The problem is when tries to access attribute with a specific name, how Python lookup this attribute internally and what is the priority queue？I try to answer this question first with a diagram and then explanation, finally with example to demonstrate.

## The lookup order diagram

Here is how an instance of type `SomeClass` named `ins` tries to access attribute named `dsp` in our previous example. Always remember everything in Python is `object` and `SomeClass` and `ins` are all `object` by themselves and has their own attributes.

![Python_attribute_lookup_order.drawio.png](/assets/images/Python_attribute_lookup_order.drawio.png)

## Explanation

In the diagram, from top to down:

1. Everything starts with `__getattribute__` method
2. Check whether ‘dsp’ is one of the attributes of `SomeClass`, note that this include all attributes inherited from parent classes
3. If yes in above step, check whether it’s a data descriptor, if yes return:
    1. return `__get__` method result if it has this method
    2. return this object if no `__get__` method
4. Check if ‘dsp’ is instance attribute, if yes return this attribute
5. Check again whether ‘dsp’ is one of attribute of `SomeClass`, this time check whether it’s non-data descriptor:
    1. return `__get__` method result if has this method(non-data descriptor)
    2. return this object if no `__get__` method
6. Call user defined back up method `__getattr__` if it’s defined
7. Raise `AttributeError`

## Example

```python
class DataDescriptor:
    """data descriptor"""

    def __set_name__(self, owner, name):
        self.self_name = name

    def __get__(self, obj, obj_type=None):
        return 42

    def __set__(self, obj, value):
        print("Descriptor is being set")

class NonDataDescriptor:
    """non-data descriptor"""

    def __get__(self, obj, obj_type=None):
        return 42

class SomeClass:
    """Some class that use descriptor"""

    # This descriptor has highest access priority
    dsp = DataDescriptor()
    # This access priority is below instance variables
    ndsp = NonDataDescriptor()

    def __init__(self) -> None:
        self.dsp = 'Tom'  # This dsp is a descriptor
        self.ndsp = 'Jerry'  # This ndsp is not a descriptor, it's instance variable

ins = SomeClass()
print(ins.dsp)  # 42
print(ins.ndsp)  # 'Jerry'
```

Output:

```python
Descriptor is being set
42
Jerry
```

# Refresh our Python concept

With knowledge of descriptors we can have a deeper understanding of many Python basic concept and how they work under the hood.

## Functions and methods

The only difference between functions and methods is methods have the first argument reserved for instance. In Python everything is `object`, so does functions and methods.

Here is the Python implementation of function and method in the official doc:

```python
# This is method class
**class MethodType:
    "Emulate PyMethod_Type in Objects/classobject.c"

    def __init__(self, func, obj):
        self.__func__ = func
        self.__self__ = obj

    def __call__(self, *args, **kwargs):
        func = self.__func__
        obj = self.__self__
        return func(obj, *args, **kwargs)

# This is function class
class Function:
    ...

    def __get__(self, obj, objtype=None):
        "Simulate func_descr_get() in Objects/funcobject.c"
        if obj is None:
            return self
        return MethodType(self, obj)**
```

From the code we can draw following conclusions:

- Functions are non-data descriptors
- When we define a method in class, we actually create a non-data descriptor
- When we call the method, we actually access the non-data descriptor by calling the `__get__` method of Function, this method returns a `MethodType` that is a callable and will pass the instance as the first argument to the function together with other arguments.

## @classmethod

The @classmethod decorator turns the functions user defined into a non-data descriptor of type `ClassMethod`

```python
# Simplified implementation of ClassMethod
class ClassMethod:
    "Emulate PyClassMethod_Type() in Objects/funcobject.c"

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, cls=None):
        if cls is None:
            cls = type(obj)
        return MethodType(self.f, cls)
```

From the code we can clearly see that the only difference between instance method and class method is that instance method when accessed returns a `MethodType` that accept instance `self` as parameter while class method when access returns a `MethodType` that accept class instance `cls` as parameter. Except for that, there is no other differences.

## @staticmethod

The @staticmethod decorator turns the functions user defined into a non-data descriptor of type `StaticMethod`

```python
class StaticMethod:
    "Emulate PyStaticMethod_Type() in Objects/funcobject.c"

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, objtype=None):
        return self.f

    def __call__(self, *args, **kwds):
        return self.f(*args, **kwds)
```

This descriptor do not use `obj` and `objtype` parameter, which means is does not pass instance or class object to the function. This means the function has nothing to do with this class, except that itself is a descriptor of the class.

## @property

### property is a data descriptor

`property` class is a data descriptor class that implement descriptor protocol method that can wrap functions inside them

```python
class SomeClass:
    cate = 'People'

    def __init__(self, name) -> None:
        self.name = name

    def getter(self):
        print('getter method called')
        return 42

    def setter(self, value):
        print('setter method called')
        raise Exception('can not set')

    # Here property is a class that implement descriptor protocol
    # getter and setter functions are passed to property class memebers and will be called in  __get__ and __set__
    # function. So when attr is accessed throuth dot, getter and setter will be called
    # Note that when accessed using dot, the owner class instance and class will be passed to __get__ and __set__
    # then getter and setter parameters will be managed inside __get__ and __set__
    # This already sounds very much like decorators.
    attr = property(getter, setter)

some = SomeClass('Tom')
# Call getter
x = some.attr
print(x)
# Call setter
some.attr = 5
print(some.attr)
```

Output:

```python
getter method called
42
setter method called
Traceback (most recent call last):
  File "/Users/shanweiqiang/sketch/test.py", line 29, in <module>
    some.attr = 5
  File "/Users/shanweiqiang/sketch/test.py", line 13, in setter
    raise Exception('can not set')
Exception: can not set
```

### With a little syntactic sugar—@property decorators

```python
class SomeClass:
    cate = 'People'

    def __init__(self, name) -> None:
        self.name = name

    # Here the @property decorator convert 'getter' into a descriptor of SomeClass
    # 'property' is itself a decorator that implement descriptor protocol
    @property
    def getter(self):
        print('getter method called')
        return 42

    # 'getter' is alreay a descriptor, here use the method setter to decorate 'setter' of SomeClass
    # Note the two 'setter' names:
        # in @getter.setter, the setter is method of class property
        # in def setter(..).., the setter is method of SomeClass, this method will be registered into 'getter' descriptor, the name doesn't really matters here
    @getter.setter
    def setter(self, value):
        print('setter method called')
        raise Exception('can not set')

some = SomeClass('Tom')
# Equals: some.getter.__get__(..)
x = some.getter
print(x)
# Equals: some.getter.__set__(..)
some.setter = 4
print(some.getter)
```

Output:

```python
getter method called
42
setter method called
Traceback (most recent call last):
  File "/Users/shanweiqiang/sketch/test.py", line 29, in <module>
    some.setter = 4
  File "/Users/shanweiqiang/sketch/test.py", line 21, in setter
    raise Exception('can not set')
Exception: can not set
```

# Summary

Descriptor is the mechanism behind some Python features. Knowing them is not a prerequisite to use Python. But understanding them can help to write more concise and structured code. In the end it’s for the curious.
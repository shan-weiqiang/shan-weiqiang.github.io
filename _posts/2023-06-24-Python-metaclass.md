---
layout: post
title:  "python metaclass"
date:   2023-06-24 19:22:46 +0800
tags: [python]
---

This article tries to explain how metaclass work in Python and the process of creation of class instance and class itself.

# Reference

I reference following articles and some of the content derives from them, please read them first and credit goes for the writers too:

[Understanding Python metaclasses - … and Python objects in general](https://blog.ionelmc.ro/2015/02/09/understanding-python-metaclasses/#prior-articles)

[why keyword argument are not passed into __init_subclass__(..)](https://stackoverflow.com/questions/76413508/why-keyword-argument-are-not-passed-into-init-subclass/76414882?noredirect=1#comment134772711_76414882)

[3. Data model](https://docs.python.org/3/reference/datamodel.html)

The reason I write this article is because none of these articles can fully express my understanding of metaclass(or I cannot fully understand these articles myself…), so I express my notion of metaclass by myself.

Basic concepts will not be explained here, I go directly into the instance and class creation process. At the end of the article, a fully example will be given and detailed comments will explain the code.

# Instance creation

The creation process of Python class instance can be summarized in following diagram:

![PythonObjectCreation.drawio.png](/assets/images/PythonObjectCreation.drawio.png)

1. When instance of a class is created, `__call__` of the class’s metaclass is called, with the class object as the first parameter `self` and all other user defined positional and keyword arguments
2. Inside `__call__` method, class’s `__new__` method will be called to return the created instance object
3. If success, `__call__` will call `__init__` to initialize the created instance and return the created instance

# Class creation

The creation process of Python class is more complex and can be summarized in following diagram:

![PythonObjectCreation.drawio-2.png](/assets/images/PythonObjectCreation.drawio-2.png)

1. First the Python runtime will call `__prepare__` of metaclass to return a namespace dict
2.  `__call__` of the class’s meta-metaclass is called, passing following arguments
    1. Metaclass
    2. Class name to be created
    3. A tuple containing all base classes
    4. Dict containing namespace key value patterns(created by `__prepare__` )
    5. Any other user defined keyword arguments
3. `__call__` calls `__new__` of metaclass, passing all above arguments
4. Inside `__new__` , `__init_subclass__` of the nearest base class will be called, passing only keywords arguments
5. `__new__` return the created class object
6. `__call__` call `__init__` of metaclass to do initialization, arguments are the same with `__new__` except that the first argument now is the newly created class object
7. `__call__` return the  class object

# Full example

```python
"""
Preface
    Before we go into detail about these special methods, one thing has to be clarified about arguments:
        1. For these methods inside a class(subclass of object)
            a. The first positional arguments: 
                __call__: instance object
                __new__: class of instance that about to be created; by default object only accept this arguments
                __init__: instance object
            b. The rest of positional arguments and keyword arguments
                The rest of positional arguments and keyword arguments will be passed to __new__ and __init__ by 
                metaclass of this class's __call__
        2. For these methods inside a metaclass(subclass of type):
            a. The first positional arguments:
                The same as those inside a class
            b. The rest of positional arguments and keyword arguments:
                classname
                base class tuple
                namespace dict
                any keyword arguments
            c. metaclass of this metaclass(normally type itself)'s __call__ have all those arguments
                __call__ pass arguments in b to __new__
                __new__ pass any keywords arguments to __init_subclass__ of the most close base class
                __call__ pass arguments in b to __init__
                

About __call__ instance method:
    1. __call__ method make instances of the owner class callable
    2. This applies to class and metaclass, and meta-metaclass. 
    3. __call__ is instance method, the first argument is the object who calls this method, whether it's class instance or class
    4. ALL creation of class and variable starts from type.__call__(*args, **kwargs)
        a. For metameta class it returns a class object
        b. For metaclass it returns a variable abject
    5. Whenever a(), a.__class__.__call__ is called, inside this call, type.__call__ is called 
    6. For __call__ of metaclass(subclass of type), should return super().__call__,since the object of metaclass is to create class
    7. For __call__ of class, no requirement on return value
    8. Arguments of __call__ for metaclass:
        a. The first argument is the instance(class object) which calls the method
        b. followed by three positional arguments: class name, base class tuple, namespace dict
        c. followed by any keyword arguments
    9. Arguments of __call__ for class:
        a. The first arguments is the variable instance which calls the method
        b. followed by any positional and keyword arguments that __call__ method defines

About __prepare__ class method(must be explicitly declared using @classmethod):
    When create class using class keyword, __prepare__ method of the metaclass is used to return a namspace dict
    ! No __prepare__ called when creating class dynamically

From https://docs.python.org/3/reference/datamodel.html#object.__new__

About __new__ static method:
    object.__new__(cls[, ...])
    Called to create a new instance of class cls. __new__() is a static method (special-cased so you need not declare it as
    such) that takes the class of which an instance was requested as its first argument. 
    The remaining arguments are those passed to the object constructor expression (the call to the class). 
    The return value of __new__() should be the new object instance (usually an instance of cls).

About __init__ instance method:
    object.__init__(self[, ...])
    Called after the instance has been created (by __new__()), but before it is returned to the caller. 
    The arguments are those passed to the class constructor expression. If a base class has an __init__() method, 
    the derived class’s __init__() method, if any, must explicitly call it to ensure proper initialization of the 
    base class part of the instance; for example: super().__init__([args...]).
"""

class MetaMeta(type):
    """
    Normally this should be type itself, here just used to print info
    """

    def __call__(self, class_name, base_class_tuple, namespace_dict, **kwargs):
        print(
            f"MetaMeta __call__ with {self}, {class_name},{base_class_tuple},{namespace_dict}, {kwargs}")
        # if MetaMeta is used as metaclass for another metaclass, this returns a class object
        ret = super().__call__(class_name, base_class_tuple, namespace_dict, **kwargs)
        print(f"MetaMeta __call__ return")
        return ret

class Meta(type, metaclass=MetaMeta):
    """
    This is a metaclass, because it's subclass of type; also it use MetaMeta as metaclass, so metaclass can also has metaclass, but normally
    metaclass's metaclass is type, here just to print infomation; if we change to metaclass=type, it's also ok:
    Meta(type, metaclass=MetaMeta) == Meta(type) == Meta(type, metaclass=type)
    We can see that metaclass do not have multiple hierachy, since all metaclass directly subclass type itself
    """

    @classmethod
    def __prepare__(cls, class_name, base_class, **kwargs):
        print(
            f"Meta __prepare__ with {cls}, {class_name},{base_class} {kwargs}")

        class VerboseDict(dict):
            def __init__(self, name):
                self.name = name

            def __setitem__(self, name, value):
                print(f"{self.name} assignment {name}={value}")
                if name == "__annotations__":
                    value = VerboseDict("   annotations")
                super().__setitem__(name, value)
        print(f"Meta __prepare__ return")
        return VerboseDict("ns")

    def __call__(self, *args, **kwargs):
        """
        Always return a instance of class(which is instance of Meta), since the instance of metaclass is class, class are callable to return
        a class instance
        """
        print(
            f'Meta class __call__ with {self}, {args}, {kwargs}')
        # when class created by Meta is instantiated, this line return the created variable
        ret = super().__call__(*args, **kwargs)
        print(f'Meta __call__ method return')
        return ret

    def __new__(cls, class_name, base_class_tuple, namespace_dict, **kwargs):
        print(
            f"Meta __new__ with {cls}, {class_name}, {base_class_tuple}, {namespace_dict}, {kwargs}")
        ret = super().__new__(cls, class_name, base_class_tuple, namespace_dict, **kwargs)
        print(f"Meta __new__ return")
        return ret

    def __init__(self, class_name, base_class_tuple, namespace_dict, **kwargs):
        """
        Unlike __init__ of class object, __init__ of metaclass's positional arguments is fixed:
            1. self: class being created
            2. args:
                class name
                base class tuple
                namespace dict
            3. keyword argument provided by user class definition
        """
        print(
            f"Meta __init__ with {self}, {class_name}, {base_class_tuple}, {namespace_dict}, {kwargs}")
        print(f"Meta __init__ return")

class Base:
    def __init_subclass__(cls, **kwargs):
        """
        This is classmethod, when subclass are created, type.__call__ method will call this method and pass class object created as cls
        """
        print(f"Base __init_subclass__ with {cls}, {kwargs}")
        super().__init_subclass__()
        print(f"Base __init_subclass__ return")

print(f">>>>>>> dynamcally creating class<<<<<<<<<<<<<<", end='\n\n')

def f(self, *args, **kwargs):
    print(f"someclass __init__ with {args} {kwargs}")

SomeClass = Meta('SomeClass', (Base,), {'x': 10, '__init__': f}, foo='bar')
"""
This line dynamically create class SomeClass, this will call MetaMeta.__call__ and pass all arguments to it:
Parameters：
    positional arguments:
        'SomeClass':            class name
        (Base,):                tuple containing all base classes
        {'x':..}:               namespace dict containing all class variables and methods

    keyword arguments:
        foo='bar'
    
    The number and meaning of positional arguments is fixed for metaclass's __call__
    keywords parameter can be user defined. __call__ will pass these positional and keyword arguments to __new__
    and __init__, and inside __new__,  keyword arguments will be passed to __init_subclass__ in base class

    Meta.__prepare__ will NOT be called in dynamically created class!!
"""

print(f">>>>>>> using class keyword creating class<<<<<<<<<<<<<<", end='\n\n')

class MyClass(Base, metaclass=Meta, bar='foo'):
    """
    Equals to MyClass = Meta('MyClass', ('Base',),{'data':10, '__call__':...},{'bar':'foo'})
    """
    data = 10

    def __call__(self, *args, **kwargs):
        """
        Might not return a value, since instance of class is normal variable, callable variable might not need to return
        anything
        """
        print(f'MyClass __call__ with {self}, {args}, {kwargs}')
        """
        For normal classes, whose base class is 'object', which does not have __call__ method
        For metaclass, whose base class is 'type', the __call__ method must be called to return a class instance
        """
        # Cannot access member "__call__" for type "object"   Member "__call__" is unknown
        # ret = super().__call__(*args, **kwargs)
        print(f'MyClass __call__ method return')

    def __new__(cls, *args, **kwargs):
        print(f"MyClass __new__ with {cls} {args} {kwargs}")
        ret = super().__new__(cls)
        print(f"MyClass __new__ return")
        return ret

    def __init__(self, *args, **kwargs):
        """
        Will be called by Meta.__call__ method, and pass all user arguments inside MyClass(..) to this
        If there there are no matching __init__ to accept these arguments there will be TypeError
        """
        print(f"MyClass __init__ with {self}, {args}, {kwargs}")
        print(f"MyClass __init__ return")

print(f">>>>>>> class instantiation<<<<<<<<<<<<<<", end='\n\n')
# This calls __call__ of Meta, since the __class__ of MyClass is Meta, and pass instance MyClass as first argument
a = MyClass('Bonjure', foo='Nihao')
print(f">>>>>>> callable instance<<<<<<<<<<<<<<", end='\n\n')
# This calls __call__ of MyClass, since the __class__ of a is MyClass, and pass instance a as first argument
a(foo='Hello')
```

Output:

```python
>>>>>>> dynamcally creating class<<<<<<<<<<<<<<

MetaMeta __call__ with <class '__main__.Meta'>, SomeClass,(<class '__main__.Base'>,),{'x': 10, '__init__': <function f at 0x100cd2160>}, {'foo': 'bar'}
Meta __new__ with <class '__main__.Meta'>, SomeClass, (<class '__main__.Base'>,), {'x': 10, '__init__': <function f at 0x100cd2160>}, {'foo': 'bar'}
Base __init_subclass__ with <class '__main__.SomeClass'>, {'foo': 'bar'}
Base __init_subclass__ return
Meta __new__ return
Meta __init__ with <class '__main__.SomeClass'>, SomeClass, (<class '__main__.Base'>,), {'x': 10, '__init__': <function f at 0x100cd2160>}, {'foo': 'bar'}
Meta __init__ return
MetaMeta __call__ return
>>>>>>> using class keyword creating class<<<<<<<<<<<<<<

Meta __prepare__ with <class '__main__.Meta'>, MyClass,(<class '__main__.Base'>,) {'bar': 'foo'}
Meta __prepare__ return
ns assignment __module__=__main__
ns assignment __qualname__=MyClass
ns assignment __doc__=
    Equals to MyClass = Meta('MyClass', ('Base',),{'data':10, '__call__':...},{'bar':'foo'})

ns assignment data=10
ns assignment __call__=<function MyClass.__call__ at 0x100c044a0>
ns assignment __new__=<function MyClass.__new__ at 0x100d7a020>
ns assignment __init__=<function MyClass.__init__ at 0x100d7a200>
ns assignment __classcell__=<cell at 0x100d87940: empty>
MetaMeta __call__ with <class '__main__.Meta'>, MyClass,(<class '__main__.Base'>,),{'__module__': '__main__', '__qualname__': 'MyClass', '__doc__': "\n    Equals to MyClass = Meta('MyClass', ('Base',),{'data':10, '__call__':...},{'bar':'foo'})\n    ", 'data': 10, '__call__': <function MyClass.__call__ at 0x100c044a0>, '__new__': <function MyClass.__new__ at 0x100d7a020>, '__init__': <function MyClass.__init__ at 0x100d7a200>, '__classcell__': <cell at 0x100d87940: empty>}, {'bar': 'foo'}
Meta __new__ with <class '__main__.Meta'>, MyClass, (<class '__main__.Base'>,), {'__module__': '__main__', '__qualname__': 'MyClass', '__doc__': "\n    Equals to MyClass = Meta('MyClass', ('Base',),{'data':10, '__call__':...},{'bar':'foo'})\n    ", 'data': 10, '__call__': <function MyClass.__call__ at 0x100c044a0>, '__new__': <function MyClass.__new__ at 0x100d7a020>, '__init__': <function MyClass.__init__ at 0x100d7a200>, '__classcell__': <cell at 0x100d87940: empty>}, {'bar': 'foo'}
Base __init_subclass__ with <class '__main__.MyClass'>, {'bar': 'foo'}
Base __init_subclass__ return
Meta __new__ return
Meta __init__ with <class '__main__.MyClass'>, MyClass, (<class '__main__.Base'>,), {'__module__': '__main__', '__qualname__': 'MyClass', '__doc__': "\n    Equals to MyClass = Meta('MyClass', ('Base',),{'data':10, '__call__':...},{'bar':'foo'})\n    ", 'data': 10, '__call__': <function MyClass.__call__ at 0x100c044a0>, '__new__': <function MyClass.__new__ at 0x100d7a020>, '__init__': <function MyClass.__init__ at 0x100d7a200>, '__classcell__': <cell at 0x100d87940: Meta object at 0x15b6505e0>}, {'bar': 'foo'}
Meta __init__ return
MetaMeta __call__ return
>>>>>>> class instantiation<<<<<<<<<<<<<<

Meta class __call__ with <class '__main__.MyClass'>, ('Bonjure',), {'foo': 'Nihao'}
MyClass __new__ with <class '__main__.MyClass'> ('Bonjure',) {'foo': 'Nihao'}
MyClass __new__ return
MyClass __init__ with <__main__.MyClass object at 0x100d7ef50>, ('Bonjure',), {'foo': 'Nihao'}
MyClass __init__ return
Meta __call__ method return
>>>>>>> callable instance<<<<<<<<<<<<<<

MyClass __call__ with <__main__.MyClass object at 0x100d7ef50>, (), {'foo': 'Hello'}
MyClass __call__ method return
```
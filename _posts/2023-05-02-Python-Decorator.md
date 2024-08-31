---
layout: post
title:  "python decorators"
date:   2023-05-02 19:22:46 +0800
tags: [python]
---


Decorators can make code more concise and elegant. Function and class can both be decorators. When class used as decorators, the class can be either a callable or a descriptor. When function used as decorators, decorators can accept additional arguments. Decorators are syntatic sugars.

* toc
{:toc}

# Function as decorators

Functions are first class objects in Python, function decorator wraps the decorated function and return a callable entity.

```python
import time

def timer(func):
    """record function execution time"""
    def wrapper():
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
    return wrapper

@timer
def some_func():
    print('This is counted')

# Actually calls wrapper(), some_func = timer(some_func)
some_func()
```

Outputs:

```python
This is counted
execution time: 4.017300670966506e-05
```

## Decorate callable entity that accept arguments

The decorated callable entity can accept arguments:

```python
import time

def timer(func): # The decorator itself only take one callable as argument
    """record function execution time"""
    def wrapper(one, two): # The wrapper defines what argument the user should provide
        start = time.perf_counter()
        func(one, two) # wrapper pass proper argument to decorated callable
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
    return wrapper

class SomeClass:

    @timer # after the decoration, when user calls some_func, he actually calls wrapper
    def some_func(self, name):
        print(name)

SomeClass().some_func('shan')
```

Outputs:

```python
shan
execution time: 9.304843842983246e-06
```

Note:

- `timer`: it’s the decorator, it accept a callable entity and return a callable entity
- `wrapper`: it’s the callable entity that user actually calls, user pass argument to `wrapper`
- `func` or `some_func`: it’s the decorated callable entity, it’s parameter should be managed inside `wrapper`

### Make wrapper accept any arguments

Can make wrapper to accept any argument and pass to decorated callable entity directly, this way the wrapper does not need to care about the arguments that it will decorate:

```python
import time

def timer(func):
    """record function execution time"""
    def wrapper(*args, **kwargs): # accept any arguments
        start = time.perf_counter()
        func(*args, **kwargs) # pass whatever recieved to decorated callable entity
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
    return wrapper

class SomeClass:

    @timer
    def some_func(self, name):
        print(name)

SomeClass().some_func('shan')
```

## Decorate classes

When decorate the whole class, only the constructor will be decorated:

```python
import time

def timer(func):
    """record function execution time"""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
        return result
    return wrapper

@timer
class SomeClass:
    def __init__(self) -> None:
        print('creating someclass...')

    def some_method(self):
        print('some mecho')

SomeClass().some_method()
```

outputs:

```python
creating someclass...
execution time: 9.780749678611755e-06
some mecho
```

Note:

- In above example, wrapper has to return result, or else, `SomeClass()` will return `None`!!

## Multi decorators

Multi decorators can be used to one callable entity, it works like a stack:

```python
import time

def timer(func):
    """record function execution time"""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)  # second: pass argument to here
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
        return result
    return wrapper

def log(func):
    def wrapper(*args, **kwargs):  # first-hand user input arguments,
        print("First execute")
        result = func(*args, **kwargs)
        print('construct complete')
        return result
    return wrapper

@log
@timer
class SomeClass:
    def __init__(self) -> None:  # third: pass argument to here
        print('creating someclass...')

    def some_method(self):
        print('some mecho')

# calling stack: log(timer(SomeClass.__init__))
SomeClass().some_method()
```

outputs:

```python
First execute
creating someclass...
execution time: 2.114201197400689e-05
construct complete
some mecho
```

## Functions that return decorators

### What is after the @ sign

When using decorators, the name after @ sign is decorator name, **a decorator is a callable entity that accept a callable entity and return a callable entity(or a descriptor)**

```cpp
import time

def timer(func):  # The decorator itself only take one callable as argument
    """record function execution time"""
    def wrapper(one, two):  # The wrapper defines what argument the user should provide
        start = time.perf_counter()
        func(one, two)  # wrapper pass proper argument to decorated callable
        end = time.perf_counter()
        print('execution time:\t{}'.format(end-start))
    return wrapper

class SomeClass:

    # Note:  the name after @ is a decorator name
    @timer  # after the decoration, when user calls some_func, he actually calls wrapper
    def some_func(self, name):
        print(name)

SomeClass().some_func('shan')
```

### Functions that can return a decorator

To make the decorator itself also changable, we can define a function that accept arguments and return decorators according to different function parameters. Be aware that it’s the function that accept arguments, not the decorator itself:

```python
import time

# return a decorator
def name_of_timer(timer_name):
   # The decorator itself only take one callable as argument
    def timer(func):
        """record function execution time"""
        # The wrapper defines what argument the user should provide
        def wrapper(one, two):
            start = time.perf_counter()
            # wrapper pass proper argument to decorated callable
            func(one, two)
            end = time.perf_counter()
            print('execution time:\t{}, caculated by timer: {}'.format(end-start, timer_name))
        return wrapper
    return timer

class SomeClass:
		
		# here name_of_timer('Bejiasuo') returns a decorator
    @name_of_timer('Bejiasuo')
    def some_func(self, name):
        print(name)

SomeClass().some_func('shan')
```

Outputs:

```python
shan
execution time: 9.146519005298615e-06, caculated by timer: Bejiasuo
```

### Code snippet that accommdate both situations

```python
def name(_func=None, *, kw1=val1, kw2=val2, ...):  # 1
    def decorator_name(func):
        ...  # Create and return a wrapper function.

    if _func is None:
        return decorator_name                      # 2
    else:
        return decorator_name(_func)               # 3
```

> [Primer on Python Decorators – Real Python](https://realpython.com/primer-on-python-decorators/):
> 
> 1. If `name` has been called without arguments, the decorated function will be passed in as `_func`. If it has been called with arguments, then `_func` will be `None`, and some of the keyword arguments may have been changed from their default values. The `` the argument list means that the remaining arguments can’t be called as positional arguments.
> 2. In this case, the decorator was called with arguments. Return a decorator function that can read and return a function.
> 3. In this case, the decorator was called without arguments. Apply the decorator to the function immediately.

```python
import time

# return a decorator

def name_of_timer(_func=None, *, timer_name='Tom'):
   # The decorator itself only take one callable as argument
    def timer(func):
        """record function execution time"""
        # The wrapper defines what argument the user should provide
        def wrapper(one, two):
            start = time.perf_counter()
            # wrapper pass proper argument to decorated callable
            func(one, two)
            end = time.perf_counter()
            print('execution time:\t{}, caculated by timer: {}'.format(
                end-start, timer_name))
        return wrapper
    if _func:
        return timer(_func)
    # In either case, the decorator mechanism is the same:
    # 1. What after the @ sign must finally be a function name that can accept a function and return a function,
    # the returned function will be used to accept user input arguments
    # 2. If what after the @ sign is not a direct function name, instead it's a statement(call of function),
    # then the statement first be executed to return a function name
    else:
        return timer

class SomeClass:

    @name_of_timer(timer_name='Jerry')
    def some_func(self, name):
        print(name)

    @name_of_timer
    def another_func(self, name):
        print(name)

a = SomeClass()
a.some_func('shan')
a.another_func('shan')
```

Outputs:

```python
shan
execution time: 9.59634780883789e-06, caculated by timer: Jerry
shan
execution time: 2.2212043404579163e-06, caculated by timer: Tom
```

# Class as decorators

Read [Descriptors](https://shan-weiqiang.github.io/2023/04/22/Python-Descriptor.html) to fully understand class decorators

A decorator function has two characteristics:

- It accept a callable entity
- It return a callable entity

If a class can do similar things, it can also be used as decorator too. There are two ways to achieve this:

- Implement the `__call__` method to make the class instance itself callable entity, this way it can be used just like a function
    - Can decorate **function, class, method**
    - Note that whatever it decorate, after decoration, the decorated object becomes a decorator class instance. It’s specially confusing when used to decorate class method, after decoration, the class **method** becomes **class member**
- Implement descriptor protocol to make the class a descriptor, this way when used, it will automatically call `__get__` method to return a callable entity
    - Can only decorate method, to convert method to descriptor inside class, since `__get__` function only can be called when the decorator is a class attribute

## Make the class a callable entity

We use `__call__` method to make a class callable entity:

```python
import time
from typing import Any

class Timer:

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        print("Timer instance called")

a = Timer()
# This will call __call__ method
a()
```

Output:

```python
Timer instance called
```

A class that accept function as argument( `__init__()` ) and callable is the same with decorator function. So it can also be a decorator:

```python
import time
from typing import Any

class Timer:

    # Here accept a function as argument
    def __init__(self, func) -> None:
        self.func = func

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        print("Timer instance called")
        start = time.perf_counter()
        result = self.func(*args, **kwds)
        end = time.perf_counter()
        print("Execution time: {}".format(str(end-start)))
        return result

# decorate function: after decoration, some_func become a Timer instance

@Timer
def some_func(name):
    print(name)
    time.sleep(1)

# This equals: Timer(somefunc).__call__('Tome')
some_func('Tome')

# decorate class: this actually decorate __init__, remember to return the newly created instance

@Timer
class SomeClass:
    def __init__(self, name) -> None:
        self.name = name
        print(name)

    # decorate method: Warning: This makes some_method a attribute of SomeClass, not a method anymore
    @Timer
    def some_method(self, para):
        print(para)

# This equals: Timer(SomeClass.__init__).__call__('Jerry')
a = SomeClass('Jerry')
print(type(a), a.name)

# This equals: Timer(SomeClass.some_method).__call__(a, 'Hank')
# Note the a instance must be passed explicitly now, some_method now is a class memeber, not instance method anymore
a.some_method(a, 'Hank')
```

Outputs:

```python
Timer instance called
Tome
Execution time: 1.005079083
Timer instance called
Jerry
Execution time: 1.0500000000135401e-05
<class '__main__.SomeClass'> Jerry
Timer instance called
Hank
Execution time: 4.70800000007543e-06
```

## Make the class a descriptor

```python
import time
from typing import Any

class Timer:

    # Here accept a function as argument
    def __init__(self, func) -> None:
        self.func = func

    def __get__(self, owner, owner_class) -> Any:
        def wrapper(*args, **kwarg):
            print("Timer instance called")
            start = time.perf_counter()
            # Note that owner instance is passed as parameter
            result = self.func(owner, *args, **kwarg)
            end = time.perf_counter()
            print("Execution time: {}".format(str(end-start)))
            return result
        return wrapper

class SomeClass:

    # Now some_method becomes descriptor of SomeClass
    @Timer
    def some_method(self, para):
        print(para)

a = SomeClass()

# Equals: a.some_method.__get__()('Tome'), here __get__() returns the wrapper function
a.some_method('Tome')
```

Output:

```python
Timer instance called
Tome
Execution time: 2.958000000000821e-06
```

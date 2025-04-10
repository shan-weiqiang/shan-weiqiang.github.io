---
layout: post
title:  "CRTP and Mixin"
date:   2023-10-13 19:22:46 +0800
tags: [c++]
---

* toc
{:toc}

# 静态多态

## 定义与实现原理

静态多态又叫做CRTP，全程是*Curiously recurring template pattern*，是基于C++模板实现的。其方法是：一个继承类 `Derived`，它继承自一个以 `Derived`为模板参数的基类 `Base`。原理基础是：

- 模板参数的二次查找

```cpp
#include <functional>
#include <iostream>

template <typename Derived, typename ValueType> class Base {
public:
  using and_then_callback = std::function<void(ValueType &)>;

  // 1. do not repeat yourself
  Derived &derived() { return static_cast<Derived &>(*this); }
  Derived const &derived() const { return static_cast<Derived const &>(*this); }
  // 2. use decltype to return types that unknow during this time
  // but will be known at instantiation time
  decltype(auto) and_then(const and_then_callback &callback) {
    if (derived().has_data()) {
      callback(derived().get_data());
      // 3. and_then will be instantiated only at use time, at that time
      // other_implementation is already defined
      derived().other_implementation();
    }
    return derived();
  }
};

template <typename ValueType>
class Derived_A : public Base<Derived_A<ValueType>, ValueType>

{
public:
  template <typename... Argu> void set_data(Argu &&...args) {
    data = ValueType(std::forward<Argu>(args)...);
    flag = true;
  }
  ValueType &get_data() { return data; }
  void other_implementation() {
    std::cout << "Derived_A implementation is called\n";
  }
  bool has_data() { return flag; }

private:
  ValueType data;
  bool flag = false;
};

template <typename ValueType>
class Derived_B : public Base<Derived_B<ValueType>, ValueType> {
public:
  template <typename... Argu> void set_data(Argu &&...args) {
    data = ValueType(std::forward<Argu>(args)...);
    flag = true;
  }
  ValueType &get_data() { return data; }
  void other_implementation() {
    std::cout << "Derived_B implementation is called\n";
  }
  bool has_data() { return flag; }

private:
  ValueType data;
  bool flag = false;
};

struct MyType {
  int a;
  float b;
  MyType(int arg1, float arg2) : a(arg1), b(arg2) {};
  MyType() = default;
};

int main(int argc, char const *argv[]) {
  Derived_A<MyType> DA;
  Derived_B<MyType> DB;

  DA.template set_data(1u, 2.1f);
  DB.template set_data(2u, 3.2f);

  DA.and_then(
      [](MyType &a) -> void { std::cout << "from DA: a = " << a.a << "\n"; });
  DB.and_then(
      [](MyType &b) -> void { std::cout << "from DB: a = " << b.a << "\n"; });
  return 0;
}
```

## 用法一：将基类的接口扩展到继承类

当基类的方法在继承类中不存在时，会将基类的接口方法扩展到继承类。在上面的例子中， `and_then` 方法在继承类中不存在，继承类扩展了这些接口。

- 扩展后用户直接使用继承类
- 继承类必须保证在基类的方法实现中用到的所有方法，也就是说：
    - 继承类提供接口给基类
    - 基类提供接口给用户

## 用法二：实现静态接口

当继承类中有基类相同的方法时，继承类的方法会覆盖基类的方法，而通过CRTP，在基类中可以直接调用继承类的同名方法。如果用户使用基类对象，就会产生与使用虚函数相同的效果。

- 基类和继承类实现同名方法
- 在基类的同名方法中调用继承类的同名方法
- 用户直接使用基类对象，调用的是实际继承类的方法

```cpp
#include <functional>
#include <iostream>

template <typename Derived, typename ValueType> class Base {
public:
  /// 基类和继承类有相同的方法
  Derived &print_value() {
    /// 将指针cast成继承类的指针
    auto derived = static_cast<Derived *>(this);
    /// 在基类中调用继承类的同名方法
    derived->print_value();
    return *derived;
  }
};

template <typename ValueType>
class Derived_A : public Base<Derived_A<ValueType>, ValueType> {
public:
  template <typename... Argu> void set_data(const Argu &...args) {
    data = ValueType(args...);
    flag = true;
  }
  ValueType &get_data() { return data; }
  void print_value() { std::cout << "Derived_A printing\n"; }
  bool has_data() { return flag; }

private:
  ValueType data;
  bool flag = false;
};

template <typename ValueType>
class Derived_B : public Base<Derived_B<ValueType>, ValueType> {
public:
  using fn_print_value_type = std::function<ValueType &>;
  template <typename... Argu> void set_data(const Argu &...args) {
    data = ValueType(args...);
    flag = true;
  }
  ValueType &get_data() { return data; }
  void print_value() { std::cout << "Derived_B printing\n"; }
  bool has_data() { return flag; }

private:
  ValueType data;
  bool flag = false;
};

struct MyType {
  int a;
  float b;
  MyType(const int arg1, const float arg2) : a(arg1), b(arg2){};
  MyType() = default;
};

/// 用户
/// 注意这里用户必须是个模板，因为不但Derived_A和Derived_B是两种类型
/// 他们的基类也是两种类型，不能用同一个基类指针指向它们，需要使用
/// 模板函数的方式来同时支持Derived_A和Derived_B作为参数传入
/// 静态多态在使用时也是静态的
template <typename Derived, typename ValueType>
void print_base(Base<Derived, ValueType> &base) {
  base.print_value();
}

int main(int argc, char const *argv[]) {
  Derived_A<MyType> DA;
  Derived_B<MyType> DB;

  DA.template set_data(1u, 2.1f);
  DB.template set_data(2u, 3.2f);
  /// DA 和 DB 都可以传入，且分别调用各自的方法
  print_base(DA);
  print_base(DB);
  return 0;
}
```

CRTP能达到的效果是编译期的接口：

- 通过继承CRTP基类获取接口，这些接口在编译器实现，无运行时成本
  - 可以在基类接口中添加一些通用的功能实现，例如tracing/log等
- 没有共同的基类；用户直接使用继承类

## 静态多态和虚函数多态的对比

CRTP静态多态和虚函数动态多态区别在于没有 *vptr* 和 *vptr table* 等动态运行时的函数查找机制，是在编译时运用模板的特性来实现静态的多态：

- 静态多态因为没有运行时损耗，运行时效率要比动态多态要高
- CRTP要求继承类必须实现指定的函数供基类(接口类)调用，所以区别在于：
    - 动态多态要求继承类必须实现相应的虚函数
    - 静态多态要求继承类必须实现相应的成员方法，供基类接口方法调用
- 静态多态只能在模板类使用，使用范围不如虚函数
- 静态多态**没有统一的基类**，不能像动态多态那样使用一个基类接口，所以静态多态必须在编译时知晓所有的继承类
  - 可以让动态多态的基类再继承自一个统一的基类，但是这样与动态多态混合后又失去了运行时的效率

静态多态是不能完全替代虚函数的，因为静态多态要求在编译时已经知道所有的类型信息，其多态是通过模板的特化来实现的；虚函数不要求在编译时知道所有类型信息，只需要知道虚接口类型，而在运行时自动实现多态（其实运行时也不知道实际的类型信息，只是通过虚函数表实现多态）。

# Mixin

Wikipedia的定义：

> In object-oriented programming languages, a mixin (or mix-in)[1](https://en.wikipedia.org/wiki/Mixin)[3][4] is a class that contains methods for use by other classes without having to be the parent class of those other classes.
> 

根据这个定义C++并没有原生支持Mixin，因为C++必须通过模板参数+继承的方式实现Mixin。

**C++中的Mixin就是类继承它的模板参数。本质上就是继承。**

```cpp
#include <functional>
#include <iostream>

/// Mixins
class SayEn {
public:
  void say_hi() { std::cout << "Hello\n"; }
};

class SayCh {
public:
  void say_hi() { std::cout << "你好\n"; }
};

// Person is users of Mixins
template <typename Mixin> class Person : public Mixin {
public:
  // This is the general function added upon SayEn and SayCh
  void say_hi_10() {
    for (int i = 0; i < 10; ++i) {
      this->say_hi();
    }
  }
};

int main(int argc, char const *argv[]) {
  Person<SayEn> en_person;
  Person<SayCh> ch_person;

  en_person.say_hi_10();
  ch_person.say_hi_10();
}
```

以上用CRTP实现如下：

```cpp
#include <functional>
#include <iostream>

template <typename D> class Person {

public:
  void say_hi_10() {
    for (int i = 0; i < 10; ++i) {
      static_cast<D *>(this)->say_hi();
    }
  }
};

class SayEn : public Person<SayEn> {
public:
  void say_hi() { std::cout << "Hello\n"; }
};

class SayCh : public Person<SayCh> {
public:
  void say_hi() { std::cout << "你好\n"; }
};

int main(int argc, char const *argv[]) {
  SayEn en_person;
  SayCh ch_person;

  en_person.say_hi_10();
  ch_person.say_hi_10();
}
```
- Mixin是作为模板参数，用户继承这个Mixin，通用功能在用户类中实现；**其核心用法是不改变Mixin基本功能颗粒，以其为基础将功能累加扩展**
  - Mixin是非侵入式的，原有的Mixin颗粒不需要修改
- CRTP是提供基类，用户继承这个基类，通用功能在基类中实现；**其核心用法是依靠CRTP基类，提供一套编译时的通用的接口，这些接口实现通用的功能**
  - CRTP是侵入式的，继承类需要相关接口就必须继承CRTP基类

# CRTP基类用作Mixin

既然Mixin可以被作为模板参数被其他类继承其功能，那么一个CRTP的基类可以作为一个Mixin类被其他类继承，这样其他类也变成了一个CRTP的基类，且这个继承类可以重新 *override* 原CRTP基类的方法:

```cpp
#include <functional>
#include <iostream>

/// CRTP 基类
template <typename Derived> class Animal {
public:
  /// 接口方法
  void run() { this->get_child()->default_behavior(); }

  void bark() { this->get_child()->default_behavior(); }

  /// 所有基类要求实现，作为接口方法的默认实现
  void default_behavior() { exit(1); }

private:
  /// 类型转为继承类
  Derived *get_child() { return static_cast<Derived *>(this); }
};

/// Mixin

template <typename Mixin> class LivingThing : public Mixin {};

/// Pet现在也是CRTP接口类
template <typename T> class Pet : public LivingThing<Animal<T>> {};

/// 使用
class Dog : public Pet<Dog> {
public:
  void run() { std::cout << "Dog running.." << std::endl; }
  void default_behavior() {
    std::cout << "Dog is lazy, it is doing nothing.." << std::endl;
  }
};

int main() {
  Dog d;
  /// Dog没有实现bark方法，但是继承了CRTP的默认接口方法实现
  /// 注意：在CRTP基类bark方法中用到的Derived方法必须在Drived类中实现
  d.bark();
}
```

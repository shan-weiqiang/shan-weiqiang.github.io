---
layout: post
title:  "unique_ptr不完整类型案例分析"
date:   2023-12-24 19:22:46 +0800
tags: [c++]
---


本文不是介绍pimpl设计模式，而是关于在使用`std::unique_ptr`实现pimpl设计模式时出现的编译问题及原因，以及与`std::shared_ptr`实现pimpl的区别。

相关文章：

1. [smartPtr内存模型](https://shan-weiqiang.github.io/2024/04/20/smartPtr-%E5%86%85%E5%AD%98%E6%A8%A1%E5%9E%8B.html)
2. [smartPtr构造&析构行为
](https://shan-weiqiang.github.io/2024/04/21/smartPtr-%E6%9E%84%E9%80%A0-%E6%9E%90%E6%9E%84%E8%A1%8C%E4%B8%BA%E5%8C%BA%E5%88%AB.html)

* toc
{:toc}

# 问题描述

## `someclass.h`

```cpp
#include <iostream>
#include <memory>

class SomeClass
{
public:
	void do_some_thing();

private:
	class SomeClassImp;
	std::unique_ptr<SomeClassImp> ptr;
};
```

## `someclass.cpp`

```cpp
#include "someclass.h"
#include <iostream>

class SomeClass::SomeClassImp
{
public:
	void implementation()
	{
		std::cout << "implementing...\n";
	}
};
void SomeClass::do_some_thing()
{
	ptr->implementation();
}
```

## `app.cpp`

```cpp
#include "someclass.h"
int main()
{
	SomeClass some;
	some.do_some_thing();
}
```

编译以上代码编译器出现如下报错（gcc13):

```cpp
/usr/local/include/c++/9.5.0/bits/unique_ptr.h:79:16: error: invalid application of 'sizeof' to incomplete type 'SomeClass::SomeClassImp'
   79 |  static_assert(sizeof(_Tp)>0,
      |                ^~~~~~~~~~~
```

# 问题原因

直接原因是在编译编译单元`app.cpp`时，因为用户没有自定义析构函数，所以编译器会自动在`app.cpp`编译单元生成默认析构函数，而在析构成员`std::unique_ptr`时报错，因为`std::unique_ptr`析构函数需要知道模板参数类型的类型，而不能是incomplete type，而此时在`app.cpp`编译单元，`SomeClassImp`为incomplete type，所以报错。

## `std::unique_ptr`源码分析

```cpp
template <typename _Tp, typename _Dp = default_delete<_Tp>>
    class unique_ptr
    {
...
```

`std::unique_ptr`有两个模板参数，一个是指针指向的对象类型；另一个是该类型的`deleter`函数；如果用户不指定，则使用标准库默认的`default_delete<_Tp>`:

```cpp
template<typename _Tp>
    struct default_delete
    {
      /// Default constructor
      constexpr default_delete() noexcept = default;

      /** @brief Converting constructor.
       *
       * Allows conversion from a deleter for arrays of another type, @p _Up,
       * only if @p _Up* is convertible to @p _Tp*.
       */
      template<typename _Up, typename = typename
	       enable_if<is_convertible<_Up*, _Tp*>::value>::type>
        default_delete(const default_delete<_Up>&) noexcept { }

      /// Calls @c delete @p __ptr
      void
      operator()(_Tp* __ptr) const
      {
	static_assert(!is_void<_Tp>::value,
		      "can't delete pointer to incomplete type");
	static_assert(sizeof(_Tp)>0,
		      "can't delete pointer to incomplete type");
	delete __ptr;
      }
    };
```

可以看到在该`deleter`会被调用，且会判断是否是incomplete type： `static_assert(sizeof(*Tp)>0`，*  在`std::unique_ptr`析构函数中会调用这个`deleter`：

```cpp
~unique_ptr() noexcept
      {
	static_assert(__is_invocable<deleter_type&, pointer>::value,
		      "unique_ptr's deleter must be invocable with a pointer");
	auto& __ptr = _M_t._M_ptr();
	if (__ptr != nullptr)
	  get_deleter()(std::move(__ptr)); // 调用deleter
	__ptr = pointer();
      }
```

所以，在使用`std::unique_ptr`时，如果它的析构函数被编译，但是指向的类型仍然是incomplete type时，就会报错。

# 解决办法

解决办法很简单，就是让编译器在知晓`std::unique_ptr`指向的类型的具体定义后再生成`SomeClass`的析构函数，即将起析构函数的实现放在`someclass.cpp`，而不是在.`someclass.h`中默认实现：

`someclass.h`

```cpp
#include <iostream>
#include <memory>

class SomeClass
{
public:
	SomeClass();
	~SomeClass();
	void do_some_thing();

private:
	class SomeClassImp;
	std::unique_ptr<SomeClassImp> ptr;
};
```

`someclass.cpp`

```cpp
#include "someclass.h"
#include <iostream>

SomeClass::SomeClass(){}
SomeClass::~SomeClass(){}

class SomeClass::SomeClassImp
{
public:
	void implementation()
	{
		std::cout << "implementing...\n";
	}
};
void SomeClass::do_some_thing()
{
	ptr->implementation();
}
```

以上代码可以解决问题，但没有完全回答所有问题。

## 为什么构造函数也要跟随析构函数一起在cpp中实现

如上解决方案中如果仅仅在cpp文件中实现析构函数，而没有将构造函数一起实现，则会报同样的错误，问题的原因在于在构造函数时如果发生异常，编译器需要知道析构函数来讲对象析构，而此时编译器仍然会自动产生析构函数，问题跟之前一样

## 为什么析构函数可以放在SomeClassImp定义的前面

因为`std::unique_ptr`是模板，根据模板的[二次查找规则](https://shan-weiqiang.github.io/2023/05/01/C++-template-name-lookup.html)，当其析构函数被实例化时，整个编译单元的定义信息已经知道，所以即便`SomeClassImp`定义在`SomeClass`析构的后面，仍然能够正常编译。

另外参见Stackoverflow上的问题：[In pimpl design using std::unique_ptr, if dtor is put in implementation file BEFORE Impl type definition, why is it compiling ok?](https://stackoverflow.com/questions/77709516/in-pimpl-design-using-stdunique-ptr-if-dtor-is-put-in-implementation-file-bef)

# 用`std::unique_ptr`而不是`std::shared_ptr`

如果使用`std::shared_ptr`，而不是`std::unique_ptr`来实现pimpl，以上遇到的所有问题都会消失，因为`std::shared_ptr`并不会将所指向对象的`deleter`：

```cpp
template<typename _Tp>
    class shared_ptr : public __shared_ptr<_Tp>
    {
...
```

那为什么不使用`std::shared_ptr`，而是使用`std::unique_ptr`呢？ 有如下的原因：

- pimpl的设计默认定义了模糊指针指向的对象应该唯一的属于当前对象，`std::unique_ptr`完美实现了这一点
- `std::unique_ptr`有更好的运行时性能：不需要control block，没有引用计数等原子操作

# 最佳实践

- 对于包含`std::unique_ptr`的pimpl类，在cpp文件中定义析构函数和构造函数
- 使用`std::unique_ptr`，而不是`std::shared_ptr`
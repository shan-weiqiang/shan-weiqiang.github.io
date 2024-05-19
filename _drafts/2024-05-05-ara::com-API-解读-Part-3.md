---
layout: post
title:  "ara::com API 解读[Part 1]"
date:   2024-05-05 13:22:46 +0800
tags: [AUTOSAR]
---

[ara::com API](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_EXP_ARAComAPI.pdf)是理解AUTOSAR AP中面向服务架构的入口。无论对于底层BSW开发，模型和代码引擎开发，还是对于上层应用开发，都是需要理解的。可以说ara::com API是应用层开发、BSW开发、模型/代码引擎开发的三者交汇点。理解它非常重要。本文是第三部分。

---
**WARNING**

本文不是翻译，是对原文的注解，所有信息请以原文为准。

---

---
**NOTE**

以下文中用到的词语解释：

- *通信协议*，*驱动协议*： 如果不是特别说明，这里*通信协议*指的是ComAPI底层使用的通信驱动协议，例如DDS、SOME/IP。注意**不是**网络协议
- *ComAPI*, *ComAPI绑定*，*绑定层*，*绑定*，*适配层*：这些都是指ComAPI层的接口实现，也称作绑定实现；它是存在于应用层与通信协议之间的适配代码
- *Proxy*，*Proxy类*，*客户端*：如无特别说明，都是指服务的消费方，Proxy接收Skeleton提供的服务
- *Skeleton*，*Skeleton类*，*服务端*：如无特别说明，都是指服务提供方，Skeleton为Proxy提供服务
- *服务实例*，*Skeleton类实例*，*Skeleton实例*：都是指一个具体的服务实例， 它是Skeleton类的实例；服务实例全局唯一
- *消费实例*，*Proxy类实例*， *Proxy实例*：是指一个具体的消费方，它有唯一的Client ID; 注意Proxy实例是没有服务实例ID的，服务ID是Skeleton实例的唯一标识符
- Skeleton/Proxy的**实例**与Seleton/Proxy**类**是两个概念，文中如果指的是实例，则会具体写明，否则指的是Skeleton/Proxy类本身

---

* toc
{:toc}


### 5.3.6 Methods

> The operator contains all of the service methods IN-/INOUT-parameters as INparameters. That means INOUT-parameters in the abstract service method description
are split in a pair of IN and OUT parameters in the ara::com API.

---
**NOTE**

服务接口中的每一个method都对应一个实现了`()`操作符的类。`()`操作符的入参就是method的In+In/Out参数；返回值是`ara::core::Future`类型，其模板参数类型是一个封装了这个method所有的Out+In/Out类型的结构体。关于In/Out类型，AUTOSAR规定要将其分别放在入参和返回值中，而不是通过非常量引用或者指针形式传入参数，然后通过引用或者指针原地返回结果。也就是说In/Out method参数类型，只是一个语法糖，等同于分别在In,Out中分别增加一个相同类型的参数。不支持通过引用或者指针原地返回结果的原因也很简单：method的返回类型是一个`future`，且必须马上返回，而不是block等待；如果入参是一个非常量引用或者指针，则method的调用依赖于周围的环境，则必须block等待，失去了method调用的异步特性。

---

#### 5.3.6.1 One-Way aka Fire-and-Forget Methods

fire-and-forget模式返回类型为`void`，但是返回`void`的方法不一定是fire-and-forget:

- fire-and-forget method的Proxy端不会等待Skeleton端的返回结果，而是在讲数据发送到网络后直接在本地的`promise`中`set_value`
- 返回值为`void`但不是fire-and-forget的method，即便返回值是`void`，Proxy端也要在接收到Skeleton端的通知后才会讲`promise`设置值，即便这个值是`void`

#### 5.3.6.2 Event-Driven vs Polling access to method results

AUTOSAR method对事件event-driven和polling的支持是通过对[std::future](https://en.cppreference.com/w/cpp/thread/future)的扩展实现的:

- event-driven: AUTOSAR的`ara::core::Future`实现了如下接口，使`future`可以注册一个callback，当数据可用时直接异步回调

```c++
template <typename F>
auto then(F&& func) -> Future<SEE_COMMENT_ABOVE>;
```
这个callback被调用的线程可能是`then`被调用的线程；也可能是`promise`的`set_value`线程

- polling: AUTOSAR的`ara::core::Future`提供`bool is_ready() const;`，这个接口是non-blocking的，如果返回`true`，则`wait`肯定不会block

#### 5.3.6.3 Canceling Method Result


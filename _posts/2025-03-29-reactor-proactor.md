---
layout: post
title:  "Reactor and Proactor keynotes"
date:   2025-03-29 19:22:46 +0800
tags: [linux]
---


Following content aggregates materials about *reactor* and *proactor*, along with some keynotes about it.

## References

- [Reactor and Proactor, Examples of event handling patterns](../assets/files/tpd_reactor_proactor.pdf): Great material on what is reactor and what is proactor.
- [The Proactor Design Pattern](../assets/files/The%20Proactor%20Design%20Pattern.pdf): Explains the boost.asio proactor design pattern. What is key about this material is that it also explains the relation ship between reactor and proactor in Linux: proactor is implemented on top of reactor(epoll).
- [Proactor Wikipedia](https://en.wikipedia.org/wiki/Proactor_pattern): The wiki page reveals an important fact about proactor: **The proactor pattern can be considered to be an asynchronous variant of the synchronous reactor pattern.**

## Keynotes

- Reactor in Linux has native OS support through system primitives like `epoll`. But Linux does not have native support for proactor. Windows have native support for proactor, IOCP
- In Linux, proactor is implemented on top of reactor.
- Reactor is *synchronous* I/O, while proactor is *asynchronous* I/O.
- Again and important: **The proactor pattern can be considered to be an asynchronous variant of the synchronous reactor pattern.**
- Reactor in Linux can be simplified as I/O multiplexing

## Exectuion Context

One thing that have long been confusing me about proactor is it's execution context.





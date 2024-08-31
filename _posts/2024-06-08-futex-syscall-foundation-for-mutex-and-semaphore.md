---
layout: post
title:  "futex: foundation of linux synchronization"
date:   2024-06-08 19:20:46 +0800
tags: [linux-programming]
---

In linux, pthread mutex `pthread_mutex_t`(on which `std::mutex` is based),  and `pthread_cond_t`(on which `std::condition_variable` is based), and semaphores, all use futex kernel support as their internal implementation. Let't dig into what is futex and the behavior of it.

Reference: 
[futex](https://www.man7.org/linux/man-pages/man2/futex.2.html)
[syscall](https://man7.org/linux/man-pages/man2/syscalls.2.html)

## futex behavior

futex is called fast user-space locking. At first glampse it's confusing since futex is a syscall with following signature:

```c
long syscall(SYS_futex, uint32_t *uaddr, int futex_op, uint32_t val,
                    const struct timespec *timeout,   /* or: uint32_t val2 */
                    uint32_t *uaddr2, uint32_t val3);
```

Why it is called *user-space* locking when it needs kernel support? The answer is the second parameter `uaddr`, which is a user space 32-bit word. `uaddr` is a user space address inside the calling process, it serves two purposes:

- threads do compare-and-swap operations on this integer to change the value, in user mode; threads do futex syscall operations through this address, which **is used to connect the synchronization in user space with the implementation of blocking by the kernel**. 
- kernel transform this userspace `uaddr` into a unique identifier and use it to maintain a unique threads waiting list; kernel accept user space syscalls which pass `uaddr` into kernel space, then kernel does corresponding operations, such as put thread into waiting list, or wake up specific number of threads in the waiting list. There are mainly two operations the kernel does:
  - `FUTEX_WAIT`: put the calling thread into the waiting list uniquely identified by `uaddr`, if and only if the value in `uaddr` is equal to `val`; if `uaddr` is not equal to `val`, the syscall returns immediately. Above operations are done atomically.
  - `FUTEX_WAKE`: wake up `val` number of threads in the waiting list uniquely identified by `uaddr`. There is no operations on the value in `uaddr`

The functionality futex provides is basically a threads queue and dequeue mechanism. Even though mutex, condition variable, semaphore are all implemented on top of futex, the kernel knows nothing about the real usage of these concept. What the kernel knows is when to put a thread into a unique waiting list and when to remove a thread from a unique waiting list, all of which are provoked by user. Kernel provides a *service*, it's up to user for how to used it and what it is used for.

It's useful to rethink about what exactly is a lock. At it's simplest form, lock is a binary flag, 0 or 1. What is special about locks is that they should be operated atomically. At user space, atomicity can be achieved through compare-and-swap operation. So the spinlock can be implemented without any kernel support. However, what if we want to put thread into waiting state if it currently can not get the lock to optimize the CPU resources? How to wake up threads when lock is free to use? These scheduling of threads need kernel support. futex is in the position to fulfil these needs.

Take the simplest binary lock for example, if one thread is competing for the lock, what it should do is to firstly do atomic operation to decide whether the lock is free, if it's free, the binary is flipped and the lock is aquired by this specific thread. Please note that during this process, no kernel support is needed. Since the switch from user mode to kernel mode is a costly action, the user space fast locking functionality provided by futex is indeed *fast*. If unluckily, the lock is not available after the atomic check operation, a futex syscall is required to put the calling thread into waiting list for this lock, this is when a costly kernel mode switching is needed.

## intra-process and inter-process synchronization

From the perspective of a process the futex word is in the address space of current process. If two threads come from this same process, it is obviously no problem if the same futex word is used, since they shared the futex in the same address space. futex word can be a global variable in this scenario. 

What if threads from two different process want to do synchronization using futex? It's intuitive to think that the futex word should be in a shared memory region. This is indeed the solution. If the futex word is in a shared memory region from different processes, *inter-process* synchronization can be achieved. It is rather easy from the user side, since what the user need to do is simply create a shared memory region and put the futex word in there and share it across processes. The usage of the futex is totally the same as in non-shared memory scenario. However, the kernel now has a headache to solve: how to uniquely identify inter-process futex？

In intra-process scenario, the kernel can use PID plus the virtual address of the futex word to uniquely identify a futex inside the kernel. In inter-process scenario, this is invalid since the futex word have different virtual address in each processes. The requirement is that kernel need to find a way to uniquely identify a futex, even across different virtual address space. One possible solution is to use the physical address to uniquely identify the futex, since the physical address is the same across all processes in this situation. However, the futex might be swapped out of RAM during runtime and every kernel have it’s own page replacement algorithm. After the memory region containing the futex is swapped in, it might have a different physical address with the previous one. The kernel might be implemented that the page that contains any futex word must not be swapped out. We wont' go further about the kernel implementations here, but at the end, for a inter-process futex to work, it’s kernel’s job to ensure:

  - every process that use this futex must share the same waiting list for blocking thread
  - all processes’s futex syscall works atomically on this futex word inside the kernel(user space operation on this futex word is assured by user)

`pthread_mutex_t` and named semaphores in POSIX can be used to achieve inter-process synchronization. The C++ `std::mutex` is only designed for intra-process usage.
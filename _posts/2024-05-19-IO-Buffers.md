---
layout: post
title:  "I/O buffer: user vs kernel"
date:   2024-05-19 13:22:46 +0800
tags: [linux-programming]
---

本篇文章是[The Linux Programming Interface](https://man7.org/tlpi/)(*published in October 2010, No Starch Press, ISBN 978-1-59327-220-3*)这本书第13章：*File I/O Buffering*的阅读总结及翻译。

* toc
{:toc}

# I/O缓存原理图

Linux I/O缓存分从外设到kernel之间的I/O缓存，称为kernel缓存；以及`stdio` C库到kernel之间的I/O缓存，称为`stdio`缓存：

![Alt text](/assets/images/io_buffer.png)

# stdio缓存

usr缓存即C系统库`stdio`的缓存，由于这个缓存的存在，会造成用户的期望和实际程序行为的不一致，所以理解这个缓存对写出符合期望的程序是很有用的。从原理图上就可以看出`stdio`的缓存最根本的影响就是：用户调用`stdio`做I/O，跟kernel实际接收到I/O请求是不同步的。这个落差就是用户以为做了I/O，但是kernel确还没收到请求。`stdio`会将用户的I/O数据首先copy到缓存区域，根据`stdio`的模式来进行与kernel的交互，即syscall。无论读写，`stdio`有三种缓存模式：

- IONBF: 没有缓存，所有的`stdio`调用都直接调用`write/read` syscall，相当于透传；默认情况下`stderr`是这个模式
- IOLBF: Line buffered, 行缓存，即每当读，或者写遇到`\n`换行符时，`stdio`函数才会调用`write/read`系统调用，每次读写一行。如果读写的文件描述符是一个pty设备，模式是此模式
- IOFBF: Fully buffered，全缓存，即根据用户设置或者默认的缓存大小进行缓存，只有到缓存满时，`stdio`的函数才会调用`write/read`系统调用进行kernel的读写操作；一般磁盘文件读写模式这个模式

## 设置缓存模式

`setvbuf`用于设置一个文件描述符的缓存模式：

- 每个文件描述符有自己的IO缓存模式
- `setvbuf`的设置会影响`stdio`中所有的函数对当前文件描述符的缓存模式
- 必须在当前文件描述符使用任何`stdio`函数前调用`setvbuf`

## flush缓存

根据一个流文件的打开方式，一个流可以是只读的；可以是只写的；也可以是可读可写的：

- 如果是只读的，则流文件需要一个`stdio`的read缓冲区
- 如果是只写的，则流文件需要一个`stdio`的write缓冲区
- 如果是可读可写的，C标准并没有定义是否需要为读和写分别分配缓冲区，还是使用同一个缓冲区；不过C标准规定了一些规则：
  - 写操作后不能直接跟读操作，中间必须有`fflush`， `fseek`, `fsetpos`或者`rewind`，这些操作的特点是都会清空缓存区域
  - 读操作后不能直接跟写操作，中间必须有`fseek`, `fsetpos`或者`rewind`，除非读操作读到的是EOL，此时表示文件是空的，所以是不需要读缓冲区的
  - 以上两点规定间接的定义了读和写的缓冲区的设计，只要满足了以上的标准要求，系统实现时读和写可以使用同一个缓冲区，当然也可以实现不同的缓冲区
  - 上面的规则是为了保证在应用层`stdio`读写操作的**原子性**，虽然在kernel中对一个文件的读写是原子的，但是`stdio`的读写不是原子的，如果要保证原子性，就必须在读和写之间有一个类似**读写屏障**的机制，即读和写在`stdio`层也是原子的

需要强调的是，一个流只有在使用了`stdio`时，编译器才会分配相关的缓冲区。

`fflush`用于主动刷新缓存区：

- 如果不传入任何文件描述符，这个函数刷新所有`stdio`的缓冲区
  - 每个流都有自己的`stdio`函数缓冲区，缓冲区是跟流挂钩的
- 如果流是只读的，`fflush`的作用是清空缓冲区
- 如果流被关闭，`fflush`会自动被调用
  - 这里说明如果流是可读可写的，且实现采用了单一缓存，`stdio`肯定要知道当前缓存中存储的是读还是写的缓存，不然流关闭时无法决定相应的操作

# 内核缓存

内核缓存存在于内核地址空间的buffer与外部存储例如磁盘之间。

## 数据同步和文件同步

synchronized I/O data integrity completion，表示一次内核缓存与外部存储之间的同步操作。这里的data包含的数据可分为两部分：文件本身的数据以及`metadata`，`metadata`主要包含文件的作者、大小、修改时间等等。数据同步包含的意思是：

- 对于读操作：数据从磁盘读取到内核缓存，在读之前如果有尚未完成的写磁盘的操作，则先将写磁盘完成后，再进行读操作
- 对于写操作：文件数据以及**与读文件相关**的`metadata`数据成功从内核缓存写入磁盘

文件同步是数据同步的区别在于，文件同步在写操作时要将所有的`metadata`写入到磁盘，才算是完成，比数据同步要求更为苛刻：

- `fsync(int fd)`系统调用可以完成文件的文件同步，将文件写到磁盘后返回
- `fdatasync(int fd)`系统调用可以完成文件的数据同步，将文件写入磁盘后返回

` sync(void);`系统调用会将内核缓存中的所有文件的数据写入磁盘。

## O_SYNC/O_DSYNC/O_RSYNC

在使用`open`系统调用打开文件描述符时，可以通过flag设置内核缓存到磁盘的同步方式：

- O_SYNC: 每次`write`都是文件同步，数据被写入磁盘后才返回
- O_DSYNC: 每次`write`都是数据同步，数据被写入磁盘后返回
- O_RSYNC: 与O_SYNC和O_DSYNC配合使用，将`write`的同步特性增加到`read`操作上


# I/O缓存及flush总结

![Alt text](/assets/images/io_summary.png)

# FILE与FD

`stdio`所有的操作都是针对一个`FILE`结构体，它封装了一个文件描述符以及`stdio`会用到的buffer的指针等。`int fileno(FILE *stream);`和`FILE *fdopen(int fd, const char *mode);`可以用于二者之间的转换，转换后可以使用`stdio`和`read/write`系统调用同时对文件描述符进行操作。socket和pipe创建的时候返回的是文件描述符，如果想使用`stdio`，则可以使用`fdopen`进行转换。更多详见：[11.1.1 Streams and File Descriptors](https://www.gnu.org/software/libc/manual/html_node/Streams-and-File-Descriptors.html)

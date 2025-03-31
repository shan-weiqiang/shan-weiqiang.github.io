---
layout: post
title:  "Reactor and Proactor Exectuion Context"
date:   2025-03-29 9:22:46 +0800
tags: [linux]
---


Following content aggregates materials about *reactor* and *proactor*, along with some keynotes about it.

## References

- [Reactor and Proactor, Examples of event handling patterns](https://github.com/shan-weiqiang/shan-weiqiang.github.io/blob/main/assets/files/tpd_reactor_proactor.pdf): Great material on what is reactor and what is proactor.
- [The Proactor Design Pattern: Concurrency Without Threads](https://github.com/shan-weiqiang/shan-weiqiang.github.io/blob/main/assets/files/The%20Proactor%20Design%20Pattern.pdf): Explains the boost.asio proactor design pattern. What is key about this material is that it also explains the relationship between reactor and proactor in Linux: proactor is implemented on top of reactor(epoll).
- [Proactor Wikipedia](https://en.wikipedia.org/wiki/Proactor_pattern): The wiki page reveals an important fact about proactor: **The proactor pattern can be considered to be an asynchronous variant of the synchronous reactor pattern.**

## Keynotes

- Reactor in Linux has native OS support through system primitives like `epoll`. But Linux does not have native support for proactor. Windows have native support for proactor, IOCP
- In Linux, proactor is implemented on top of reactor.
- Reactor is *synchronous* I/O, while proactor is *asynchronous* I/O.
- Again and important: **The proactor pattern can be considered to be an asynchronous variant of the synchronous reactor pattern.**
- Reactor in Linux can be simplified as I/O multiplexing.

## Execution Context

One thing that have long been confusing me about proactor is it's execution context. For reactor, it occupies one execution context(eg, a thread) and blockingly waiting for any of file descriptors to be ready for relevant events. Since in Linux proactors are implemented on top of reactor, does proactor need additional execution context? In Boost, proactor is called [*The Proactor Design Pattern: Concurrency Without Threads*](https://live.boost.org/doc/libs/1_47_0/doc/html/boost_asio/overview/core/async.html), which indicates that there are no additional threads required for proactor. Then how to implement proactor in one thread, knowing that reactor itself already occupies one thread?

The foundation here is to know that(in the context of `boost.asio`):

- There is a underlying reactor, which is normally implemented using `epoll` in Linux. 
- There is one execution context, `io_context`, which will be called in one thread `io_context.run()`, which will call `epoll` wait under the hood.
- That `epoll` can monitor multiple file descriptors and can be updated.

Yet there is one brick missing to understanding the proactor pattern: *software events*. Epoll can only monitor file descriptors, like if a file descriptor is readable, writable, etc. But proactor requires that the *epoll_wait* be unblocked if a user async operation is completed. How can epoll monitor these kinds of events? In the reactor that is used to implement proactor, there is an pre-defined additional file descriptor, it might be a pipe, uds socket, or something else, as long as it can be written and read. This fd is used to unblock *epoll_wait* whenever there is software events. For example, *epoll_wait* monitor this fd, *fd_events* and another socket fd, *fd_socket*. *fd_socket* is to read bytes from a connection. *fd_events* is a, for example, pipe. There is a async reading operation initiated by user to read n bytes from *fd_socket*, and also a completion handler is provided and registered. Now the *epoll_wait* is blocked waiting to read from *fd_socket*, and the execution context thread is suspended in OS. Now n-1 bytes are recieved from kernel and is ready to be read. The *epoll_wait* is unblocked and find that *fd_socket* is ready to read from. The reactor calls relevant callbacks to read from this socket. Since the callback only read n-1 bytes, not n bytes, which is required by the async operation, it exit the loop and give control to *epoll_wait* again. Next, the last one byte finally arrived, again the *epoll_wait* is unblocked and the registered callback is called to read the last one byte. After reading, inside the callback, it knows that the operation is finally completed as required from the async operation. It now writes the completion information to the *fd_events* and exit the loop to go back to *epoll_wait* again. This time the *epoll_wait* immediately unblocks since there are content to be read from *fd_events*, software events happen. The reactor calls relevant software events callback and process the software events. Inside the callback, it first read from the *fd_events* and knows which software events happen and according to the information,it finds the corresponding completion handler and executes it. It goes on until all completed software events handlers are executed, then goes to *epoll_wait* again.

Let's understand above process with the help of following code snippet:

{% highlight c++ linenos %}
#include "make_day_time.h"
#include <asio.hpp>
#include <memory>

#ifndef ASYNC_UDP
#define ASYNC_UDP

using asio::ip::udp;
class udp_server {
public:
  udp_server(asio::io_context &io_context)
      : socket_(io_context, udp::endpoint(udp::v4(), 5002)) {
    start_receive();
  }

private:
  udp::socket socket_;
  udp::endpoint remote_endpoint;
  std::array<char, 1> buffer;

  void start_receive() {
    socket_.async_receive_from(
        asio::buffer(buffer), remote_endpoint,
        [this](const std::error_code &error, std::size_t) {
          if (!error) {
            std::shared_ptr<std::string> msg =
                std::make_shared<std::string>(make_daytime_string());
            socket_.async_send_to(
                asio::buffer(*msg), remote_endpoint,
                [](const std::error_code &error, std::size_t) {});
            start_receive();
          }
        });
  }
};

#endif
{% endhighlight %}

- `io_context` serves as the sole execution context. It will be run inside one thread. The reactor is implemented inside `asio::io_context`
- `socket_.async_receive_from` is the asyn operation initialized from user. It provides two requirements:
    - The receive operation should fill the buffer
    - After the buffer is filled, the lambda completion handler should be called
    Inside this call, it will register:
        - Monitoring of this socket to `io_context`, when it's available to read, epoll will unblock. **Note that after the reading is completed, inside the callback registered to the reactor, it will deregister the monitoring of this socket from the reactor. Then also inside the callback, it will trigger software events to make the execution context execute completion handler in next loop of *epoll_wait*.**
        - Register software event and it's handler(the lambda) to this same `io_context`, expecting it to be called when the reading is completed. This call returns immediately. 
- Inside the lambda, `socket_.async_send_to` is called to give feedback. Again it's the same pattern as `socket_.async_receive_from` , except that this time the reactor will unblock when this socket is available to write. After the writing complete, the completion lambda is again called as software event.
- Inside the `socket_.async_send_to` completion handler, `start_receive();` is called recursively, which starts the loop again.
- Note that the send-recieve-send-recieve is executed in order.

Do not call async read and write operations before the last one is completed. There is no meaning to do that anyway:

- Interleaved read/write is meaningless, even if it is possible(I don't know if it is possible in `asio`)
- Even if the async operations are queued by `asio`(again I don't know if it is the case in `asio`), we can chain the read/write in completion handlers to have the same effect.

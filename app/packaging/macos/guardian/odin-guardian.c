/*
 * odin-guardian: the macOS app's supervisor for the Odin Desktop engine.
 *
 * The app starts this program instead of the engine. It starts the engine as its direct child, with
 * a fresh pipe as the engine's stdin (its parent link); the engine inherits stdout and stderr and no
 * other descriptor (POSIX_SPAWN_CLOEXEC_DEFAULT), and the pipe's write end stays here alone.
 *
 * Stopping is one state that only moves forward: running, grace, terminating, killing.
 *   - The app's link (this program's stdin) closing, or the app writing "S" on it when it starts a
 *     protocol shutdown, enters grace: the engine's link is closed and the grace period starts.
 *   - SIGTERM, SIGINT or SIGHUP enter terminating at once; a second one goes straight to killing.
 *   - When grace ends, the engine gets SIGTERM and the termination period starts; when that ends,
 *     it gets SIGKILL. Neither deadline waits on anything the engine does.
 * Other bytes on the link are read and ignored. The engine stays unreaped until it has exited, so a
 * signal from here can only reach it. Its exit status is passed through: its exit code, or death by
 * the same signal. Nothing here claims the engine's own descendants were stopped: they are the
 * engine's to supervise.
 *
 * The app must not kill this program before it has reaped the engine: it closes the link or sends
 * SIGTERM, then waits longer than grace plus termination.
 *
 * Usage: odin-guardian [--grace SECONDS] [--term SECONDS] -- PROGRAM [ARGUMENT...]
 * Exit status: the engine's; 2 for a usage error; 127 when the engine cannot start; 1 when
 * supervision itself fails (the engine is then killed and reaped first).
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/event.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

enum state { RUNNING, GRACE, TERMINATING, KILLING };
enum { TIMER_GRACE = 1, TIMER_TERM = 2 };
static const int forwarded[] = {SIGTERM, SIGINT, SIGHUP};

static void say(const char *message) { fprintf(stderr, "odin-guardian: %s\n", message); }

static void fail(const char *what) {
    fprintf(stderr, "odin-guardian: %s: %s\n", what, strerror(errno));
}

static int seconds(const char *text, long *out) {
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (errno || end == text || *end || value < 0 || value > 3600) return -1;
    *out = value;
    return 0;
}

static int arm(int queue, int timer, long delay) {
    struct kevent change;
    EV_SET(&change, timer, EVFILT_TIMER, EV_ADD | EV_ONESHOT, NOTE_SECONDS, delay, NULL);
    return kevent(queue, &change, 1, NULL, 0, NULL);
}

static int finish(pid_t engine) {
    int status;
    while (waitpid(engine, &status, 0) == -1) {
        if (errno != EINTR) {
            fail("waitpid");
            return 1;
        }
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        sigset_t only;
        sigemptyset(&only);
        sigaddset(&only, sig);
        signal(sig, SIG_DFL);
        sigprocmask(SIG_UNBLOCK, &only, NULL);
        kill(getpid(), sig);
        return 128 + sig;  /* not reached for a fatal signal */
    }
    return 1;
}

static int abandon(pid_t engine) {
    kill(engine, SIGKILL);
    finish(engine);
    return 1;
}

int main(int argc, char **argv) {
    long grace = 15, term = 4;
    int index = 1, separated = 0;
    while (index < argc) {
        if (!strcmp(argv[index], "--")) {
            separated = 1;
            index++;
            break;
        }
        if (index + 1 < argc && !strcmp(argv[index], "--grace")) {
            if (seconds(argv[index + 1], &grace)) break;
        } else if (index + 1 < argc && !strcmp(argv[index], "--term")) {
            if (seconds(argv[index + 1], &term)) break;
        } else {
            break;
        }
        index += 2;
    }
    if (!separated || index >= argc || argv[index][0] != '/') {
        say("usage: odin-guardian [--grace SECONDS] [--term SECONDS] -- /ABSOLUTE/PROGRAM [ARG...]");
        return 2;
    }

    /* Signals arrive only through the queue; the engine starts with its own defaults. */
    sigset_t blocked, none, defaults;
    sigemptyset(&blocked);
    sigemptyset(&none);
    sigemptyset(&defaults);
    for (size_t i = 0; i < sizeof forwarded / sizeof *forwarded; i++) {
        sigaddset(&blocked, forwarded[i]);
        sigaddset(&defaults, forwarded[i]);
    }
    sigaddset(&defaults, SIGPIPE);
    sigprocmask(SIG_BLOCK, &blocked, NULL);
    signal(SIGPIPE, SIG_IGN);

    int link[2];
    if (pipe(link) || fcntl(link[1], F_SETFD, FD_CLOEXEC)) {
        fail("pipe");
        return 1;
    }
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    if (posix_spawn_file_actions_init(&actions) || posix_spawnattr_init(&attributes)
        || posix_spawn_file_actions_adddup2(&actions, link[0], STDIN_FILENO)
        || posix_spawn_file_actions_addinherit_np(&actions, STDOUT_FILENO)
        || posix_spawn_file_actions_addinherit_np(&actions, STDERR_FILENO)
        || posix_spawnattr_setsigmask(&attributes, &none)
        || posix_spawnattr_setsigdefault(&attributes, &defaults)
        || posix_spawnattr_setflags(&attributes, POSIX_SPAWN_CLOEXEC_DEFAULT
                                    | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF)) {
        say("could not prepare the engine's start");
        return 1;
    }
    pid_t engine;
    int started = posix_spawn(&engine, argv[index], &actions, &attributes, &argv[index], environ);
    close(link[0]);
    if (started) {
        errno = started;
        fail("could not start the engine");
        return 127;
    }

    int queue = kqueue();
    if (queue == -1) {
        fail("kqueue");
        return abandon(engine);
    }
    struct kevent change;
    EV_SET(&change, engine, EVFILT_PROC, EV_ADD, NOTE_EXIT, 0, NULL);
    if (kevent(queue, &change, 1, NULL, 0, NULL) == -1) {
        if (errno == ESRCH) return finish(engine);  /* it has already exited */
        fail("watching the engine");
        return abandon(engine);
    }
    for (size_t i = 0; i < sizeof forwarded / sizeof *forwarded; i++) {
        EV_SET(&change, forwarded[i], EVFILT_SIGNAL, EV_ADD, 0, 0, NULL);
        if (kevent(queue, &change, 1, NULL, 0, NULL) == -1) {
            fail("watching signals");
            return abandon(engine);
        }
    }
    enum state state = RUNNING;
    int app_link = 1;
    EV_SET(&change, STDIN_FILENO, EVFILT_READ, EV_ADD, 0, 0, NULL);
    if (kevent(queue, &change, 1, NULL, 0, NULL) == -1) app_link = 0;  /* no usable link */

    for (;;) {
        int enter_grace = !app_link && state == RUNNING;
        int enter_terminating = 0, enter_killing = 0;
        struct kevent event;
        if (!enter_grace) {
            int got = kevent(queue, NULL, 0, &event, 1, NULL);
            if (got == -1) {
                if (errno == EINTR) continue;
                fail("kevent");
                return abandon(engine);
            }
            if (event.filter == EVFILT_PROC) return finish(engine);
            if (event.filter == EVFILT_READ) {
                char buffer[512];
                ssize_t got_bytes = read(STDIN_FILENO, buffer, sizeof buffer);
                if (got_bytes > 0) {
                    if (memchr(buffer, 'S', (size_t)got_bytes) && state == RUNNING) enter_grace = 1;
                } else if (got_bytes == 0 || (errno != EAGAIN && errno != EINTR)) {
                    EV_SET(&change, STDIN_FILENO, EVFILT_READ, EV_DELETE, 0, 0, NULL);
                    kevent(queue, &change, 1, NULL, 0, NULL);
                    app_link = 0;
                    if (state == RUNNING) enter_grace = 1;
                }
            } else if (event.filter == EVFILT_SIGNAL) {
                if (state < TERMINATING) enter_terminating = 1;
                else if (state == TERMINATING) enter_killing = 1;
            } else if (event.filter == EVFILT_TIMER) {
                if (event.ident == TIMER_GRACE && state == GRACE) enter_terminating = 2;
                else if (event.ident == TIMER_TERM && state == TERMINATING) enter_killing = 2;
            }
        }
        if (enter_grace) {
            state = GRACE;
            if (link[1] >= 0) {
                close(link[1]);
                link[1] = -1;
            }
            if (arm(queue, TIMER_GRACE, grace) == -1) enter_terminating = 1;
        }
        if (enter_terminating) {
            if (enter_terminating == 2) say("the engine did not stop within its grace period; sent SIGTERM");
            state = TERMINATING;
            if (link[1] >= 0) {
                close(link[1]);
                link[1] = -1;
            }
            kill(engine, SIGTERM);
            if (arm(queue, TIMER_TERM, term) == -1) enter_killing = 1;
        }
        if (enter_killing) {
            say(enter_killing == 2 ? "the engine did not stop after SIGTERM; sent SIGKILL"
                                   : "stop requested again; sent SIGKILL");
            state = KILLING;
            kill(engine, SIGKILL);
        }
    }
}

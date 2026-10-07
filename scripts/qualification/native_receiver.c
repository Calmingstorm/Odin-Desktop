/* P3.5 harmless GTK receiver. No commands, credentials or external documents.
 * Reuses the event/held-state measurement shape from the retained X11 and
 * Wayland receiver corpora. Native compiled executable, not interpreter argv.
 */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static GtkWidget *window, *entry, *canvas;
static unsigned buttons, keys, motion_count;
static void record(const char *kind, unsigned code) {
    printf("{\"event\":\"%s\",\"code\":%u,\"buttons\":%u,\"keys\":%u,\"motions\":%u}\n",
           kind, code, buttons, keys, motion_count);
    fflush(stdout);
}
static gboolean event(GtkWidget *widget, GdkEvent *event, gpointer data) {
    (void)widget; (void)data;
    if (event->type == GDK_BUTTON_PRESS) { buttons++; record("button_down", event->button.button); }
    else if (event->type == GDK_BUTTON_RELEASE) { if (buttons) buttons--; record("button_up", event->button.button); }
    else if (event->type == GDK_KEY_PRESS) { keys++; record("key_down", event->key.keyval); }
    else if (event->type == GDK_KEY_RELEASE) { if (keys) keys--; record("key_up", event->key.keyval); }
    else if (event->type == GDK_MOTION_NOTIFY && buttons) { motion_count++; record("stroke", 0); }
    else if (event->type == GDK_FOCUS_CHANGE) record(event->focus_change.in ? "focus_in" : "focus_out", 0);
    return FALSE;
}
static void changed(GtkEntry *field, gpointer data) {
    (void)data;
    const char *text = gtk_entry_get_text(field);
    /* The corpus uses only plain harmless ASCII; never log arbitrary data. */
    if (strspn(text, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ") == strlen(text)) {
        printf("{\"event\":\"text\",\"text\":\"%s\"}\n", text); fflush(stdout);
    }
}
static void response(GtkDialog *dialog, gint value, gpointer data) {
    (void)value; (void)data; gtk_widget_destroy(GTK_WIDGET(dialog)); record("modal_closed", 0);
}
static void dialog(GtkButton *button, gpointer data) {
    (void)button; (void)data;
    GtkWidget *child = gtk_message_dialog_new(GTK_WINDOW(window), GTK_DIALOG_MODAL,
        GTK_MESSAGE_INFO, GTK_BUTTONS_OK, "Qualification information");
    gtk_window_set_title(GTK_WINDOW(child), "P35 information");
    g_signal_connect(child, "response", G_CALLBACK(response), NULL);
    gtk_widget_show_all(child); record("modal_opened", 0);
}
static gboolean eof(GIOChannel *channel, GIOCondition condition, gpointer data) {
    (void)channel; (void)condition; (void)data; record("receiver_exit", 0); gtk_main_quit(); return FALSE;
}
static gboolean command(GIOChannel *channel, GIOCondition condition, gpointer data) {
    (void)channel; (void)data;
    if (condition & G_IO_HUP) return eof(channel, condition, data);
    char value;
    if (read(STDIN_FILENO, &value, 1) != 1) return eof(channel, condition, data);
    if (value == 'G') {
        gtk_window_resize(GTK_WINDOW(window), 760, 520);
        gtk_window_move(GTK_WINDOW(window), 110, 110); record("geometry_changed", 0);
    }
    return TRUE;
}
int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window), "P35 safe receiver");
    gtk_window_set_default_size(GTK_WINDOW(window), 700, 460);
    gtk_window_move(GTK_WINDOW(window), 80, 80);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    entry = gtk_entry_new(); gtk_widget_set_size_request(entry, 680, 65);
    canvas = gtk_drawing_area_new(); gtk_widget_set_size_request(canvas, 680, 280);
    GtkWidget *button = gtk_button_new_with_label("Information");
    gtk_box_pack_start(GTK_BOX(box), entry, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), canvas, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(box), button, FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(window), box);
    gtk_widget_add_events(entry, GDK_ALL_EVENTS_MASK);
    gtk_widget_add_events(canvas, GDK_ALL_EVENTS_MASK);
    g_signal_connect(entry, "event", G_CALLBACK(event), NULL);
    g_signal_connect(canvas, "event", G_CALLBACK(event), NULL);
    g_signal_connect(entry, "changed", G_CALLBACK(changed), NULL);
    g_signal_connect(button, "clicked", G_CALLBACK(dialog), NULL);
    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    gtk_widget_show_all(window); gtk_widget_grab_focus(entry);
    GIOChannel *input = g_io_channel_unix_new(STDIN_FILENO);
    g_io_add_watch(input, G_IO_IN | G_IO_HUP, command, NULL);
    printf("{\"event\":\"ready\",\"pid\":%ld}\n", (long)getpid()); fflush(stdout);
    gtk_main(); g_io_channel_unref(input); return 0;
}

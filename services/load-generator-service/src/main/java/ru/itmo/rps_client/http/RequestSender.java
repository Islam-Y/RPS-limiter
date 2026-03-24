package ru.itmo.rps_client.http;

public interface RequestSender {
    void send();

    default void stop() {
    }
}

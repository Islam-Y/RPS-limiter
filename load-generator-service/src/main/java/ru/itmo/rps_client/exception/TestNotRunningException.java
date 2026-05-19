package ru.itmo.rps_client.exception;

public class TestNotRunningException extends RuntimeException {
    public TestNotRunningException(String message) {
        super(message);
    }
}

package ru.itmo.rps_client.exception;

public class TestAlreadyRunningException extends RuntimeException {
    public TestAlreadyRunningException(String message) {
        super(message);
    }
}

package ru.itmo.rps_client.api;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import ru.itmo.rps_client.exception.InvalidConfigurationException;
import ru.itmo.rps_client.exception.TestAlreadyRunningException;
import ru.itmo.rps_client.exception.TestNotRunningException;

@RestControllerAdvice
public class RestExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(RestExceptionHandler.class);

    @ExceptionHandler(InvalidConfigurationException.class)
    public ResponseEntity<ErrorResponse> handleInvalidConfig(InvalidConfigurationException ex) {
        log.warn("Invalid test configuration: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(new ErrorResponse(ex.getMessage()));
    }

    @ExceptionHandler(TestAlreadyRunningException.class)
    public ResponseEntity<ErrorResponse> handleAlreadyRunning(TestAlreadyRunningException ex) {
        log.warn("Test start rejected: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.CONFLICT).body(new ErrorResponse(ex.getMessage()));
    }

    @ExceptionHandler(TestNotRunningException.class)
    public ResponseEntity<ErrorResponse> handleNotRunning(TestNotRunningException ex) {
        log.warn("Test stop rejected: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(new ErrorResponse(ex.getMessage()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class, HttpMessageNotReadableException.class})
    public ResponseEntity<ErrorResponse> handleBadRequest(Exception ex) {
        log.warn("Invalid request: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(new ErrorResponse("Invalid request"));
    }
}

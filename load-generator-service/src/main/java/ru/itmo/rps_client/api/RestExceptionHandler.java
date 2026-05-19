package ru.itmo.rps_client.api;

import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.validation.ObjectError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
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

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ErrorResponse> handleBadJson(HttpMessageNotReadableException ex) {
        String detail = extractMessage(ex);
        log.warn("Invalid JSON: {}", detail);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(new ErrorResponse("Invalid JSON: " + detail));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class})
    public ResponseEntity<ErrorResponse> handleValidation(Exception ex) {
        BindingResult result = null;
        if (ex instanceof MethodArgumentNotValidException manv) {
            result = manv.getBindingResult();
        } else if (ex instanceof BindException bind) {
            result = bind.getBindingResult();
        }
        String message = buildValidationMessage(result);
        log.warn("Validation failed: {}", message);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(new ErrorResponse(message));
    }

    private String extractMessage(HttpMessageNotReadableException ex) {
        Throwable cause = ex.getMostSpecificCause();
        String message = cause != null ? cause.getMessage() : ex.getMessage();
        if (message == null || message.isBlank()) {
            return "Malformed JSON";
        }
        return message.trim();
    }

    private String buildValidationMessage(BindingResult result) {
        if (result == null || !result.hasErrors()) {
            return "Validation failed";
        }
        List<String> parts = new ArrayList<>();
        for (FieldError error : result.getFieldErrors()) {
            parts.add(error.getField() + " " + error.getDefaultMessage());
        }
        for (ObjectError error : result.getGlobalErrors()) {
            parts.add(error.getObjectName() + " " + error.getDefaultMessage());
        }
        if (parts.isEmpty()) {
            return "Validation failed";
        }
        return "Validation failed: " + String.join(", ", parts);
    }
}

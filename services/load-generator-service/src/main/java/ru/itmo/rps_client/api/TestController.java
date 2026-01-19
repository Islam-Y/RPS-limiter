package ru.itmo.rps_client.api;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import ru.itmo.rps_client.config.TestConfig;
import ru.itmo.rps_client.service.LoadTestManager;
import ru.itmo.rps_client.service.TestExecution;

@RestController
@RequestMapping("/test")
public class TestController {
    private final LoadTestManager manager;

    public TestController(LoadTestManager manager) {
        this.manager = manager;
    }

    @PostMapping("/start")
    public TestStartResponse start(@Valid @RequestBody TestConfig config) {
        TestExecution execution = manager.start(config);
        return new TestStartResponse("started", execution.getTestId());
    }

    @PostMapping("/stop")
    public TestStopResponse stop() {
        TestExecution execution = manager.stop();
        return new TestStopResponse("stopped", execution.getTestId());
    }

    @GetMapping("/status")
    public TestStatusResponse status() {
        TestExecution execution = manager.getCurrentExecution();
        if (execution == null || !execution.isRunning()) {
            return TestStatusResponse.notRunning();
        }
        return TestStatusResponse.running(
                execution.getTestId(),
                execution.getProfile().name(),
                execution.getConfig().targetUrl(),
                execution.getConfig().profile().params(),
                execution.getConfig().concurrency(),
                execution.getElapsed().toSeconds(),
                execution.getConfig().duration().toSeconds(),
                execution.getRequestsSent(),
                execution.getErrors()
        );
    }
}

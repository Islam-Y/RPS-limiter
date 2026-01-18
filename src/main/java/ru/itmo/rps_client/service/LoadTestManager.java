package ru.itmo.rps_client.service;

import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import ru.itmo.rps_client.config.LoadGeneratorProperties;
import ru.itmo.rps_client.config.TestConfig;
import ru.itmo.rps_client.exception.TestAlreadyRunningException;
import ru.itmo.rps_client.exception.TestNotRunningException;
import ru.itmo.rps_client.http.RequestSender;
import ru.itmo.rps_client.http.RequestSenderFactory;
import ru.itmo.rps_client.metrics.LoadMetrics;
import ru.itmo.rps_client.profile.LoadProfile;
import ru.itmo.rps_client.scheduler.IntervalScheduler;
import ru.itmo.rps_client.scheduler.LoadScheduler;

@Service
public class LoadTestManager {
    private static final Logger log = LoggerFactory.getLogger(LoadTestManager.class);

    private final TestConfigValidator validator;
    private final RequestSenderFactory senderFactory;
    private final LoadGeneratorProperties properties;
    private final LoadMetrics metrics;
    private final AtomicReference<TestExecution> currentExecution = new AtomicReference<>();

    public LoadTestManager(TestConfigValidator validator,
                           RequestSenderFactory senderFactory,
                           LoadGeneratorProperties properties,
                           LoadMetrics metrics) {
        this.validator = validator;
        this.senderFactory = senderFactory;
        this.properties = properties;
        this.metrics = metrics;
    }

    public synchronized TestExecution start(TestConfig config) {
        TestExecution existing = currentExecution.get();
        if (existing != null && existing.isRunning()) {
            throw new TestAlreadyRunningException("A test is already running");
        }
        ValidatedTestConfig validated = validator.validate(config);
        metrics.resetForNewTest();
        RequestSender sender = senderFactory.create(validated.targetUri(), validated.concurrency());
        LoadScheduler scheduler = createScheduler(validated.profile(), validated.config().duration(), sender);
        String testId = UUID.randomUUID().toString();
        TestExecution execution = new TestExecution(
                testId,
                validated.config(),
                validated.targetUri(),
                validated.profile(),
                scheduler,
                metrics,
                properties.getLogInterval(),
                metrics.getTotalSent(),
                metrics.getTotalErrors()
        );
        currentExecution.set(execution);
        log.info("Starting load test {} profile={} target={} duration={}s", testId,
                validated.profile().name(), validated.targetUri(), validated.config().duration().toSeconds());
        execution.start();
        execution.completion().whenComplete((ignored, ex) -> {
            if (ex != null) {
                log.error("Load test {} failed", testId, ex);
            }
            log.info("Load test {} completed: sent={} errors={} elapsed={}s", testId,
                    execution.getRequestsSent(), execution.getErrors(), execution.getElapsed().toSeconds());
        });
        return execution;
    }

    public synchronized TestExecution stop() {
        TestExecution execution = currentExecution.get();
        if (execution == null || !execution.isRunning()) {
            throw new TestNotRunningException("No running test to stop");
        }
        execution.stop();
        log.info("Stopping load test {}", execution.getTestId());
        return execution;
    }

    public TestExecution getCurrentExecution() {
        return currentExecution.get();
    }

    private LoadScheduler createScheduler(LoadProfile profile, Duration duration, RequestSender sender) {
        return new IntervalScheduler(duration, properties.getTick(), profile, sender);
    }
}

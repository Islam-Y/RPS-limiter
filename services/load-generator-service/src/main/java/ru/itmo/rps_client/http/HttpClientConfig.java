package ru.itmo.rps_client.http;

import java.net.http.HttpClient;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import ru.itmo.rps_client.config.LoadGeneratorProperties;

@Configuration
public class HttpClientConfig {
    @Bean(destroyMethod = "close")
    public ExecutorService httpClientExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Bean
    public HttpClient httpClient(LoadGeneratorProperties properties, ExecutorService httpClientExecutor) {
        return HttpClient.newBuilder()
                .connectTimeout(properties.getHttp().getConnectTimeout())
                .executor(httpClientExecutor)
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }
}

FROM eclipse-temurin:21-jdk AS builder

WORKDIR /app
COPY gradlew build.gradle settings.gradle /app/
COPY gradle /app/gradle
RUN chmod +x gradlew
COPY src /app/src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre

WORKDIR /app
COPY --from=builder /app/build/libs/*.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]

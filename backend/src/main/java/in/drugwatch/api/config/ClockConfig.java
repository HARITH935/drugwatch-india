package in.drugwatch.api.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Time as a dependency.
 *
 * <p>Token expiry, verification windows and "has this been revoked" are all questions about now.
 * With {@code Instant.now()} scattered through the code, testing that an expired refresh token is
 * rejected means sleeping for thirty days or weakening the test to "it is not null". With a
 * {@link Clock} bean, the test moves time.
 */
@Configuration
public class ClockConfig {

    @Bean
    Clock clock() {
        return Clock.systemUTC();
    }
}

package in.drugwatch.api.shared;

import java.lang.reflect.Method;
import java.util.Arrays;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.stereotype.Component;

/**
 * Builds cache keys that include the warehouse's current alert month.
 *
 * <p>So {@code drugPages::2026-09:page:abc123} rather than {@code drugPages::abc123}. When the
 * monthly pipeline loads a new month, every key changes and the old entries are simply never asked
 * for again, expiring on their own TTL. Invalidation becomes a property of the key rather than a
 * job somebody has to run - and the failure mode that matters, serving last month's answers as
 * current, cannot happen.
 */
@Component("dataVersionKeyGenerator")
public class DataVersionKeyGenerator implements KeyGenerator {

    private final DataVersion version;

    DataVersionKeyGenerator(DataVersion version) {
        this.version = version;
    }

    @Override
    public Object generate(Object target, Method method, Object... params) {
        return version.current() + ":" + method.getName() + ":" + Arrays.deepToString(params);
    }
}

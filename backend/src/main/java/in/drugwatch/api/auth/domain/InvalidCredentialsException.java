package in.drugwatch.api.auth.domain;

/**
 * Login, refresh or verification failed.
 *
 * <p>One exception for every such failure on purpose: the message must not say <i>which</i> part
 * was wrong. "No account with that email" and "wrong password" together are a way to find out who
 * has an account here.
 */
public class InvalidCredentialsException extends RuntimeException {
    public InvalidCredentialsException(String message) {
        super(message);
    }
}

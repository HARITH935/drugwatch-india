package in.drugwatch.api.auth.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * An account.
 *
 * <p>Package-private, like the repository: nothing outside {@code auth} should hold a user row, or
 * the password hash travels wherever that object goes. Other features get the user id.
 */
@Entity
@Table(name = "users")
class UserEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** Always lower-case. The database CHECK enforces it; this keeps Java from trying otherwise. */
    @Column(nullable = false, unique = true)
    private String email;

    @Column(name = "password_hash", nullable = false)
    private String passwordHash;

    @Column(nullable = false)
    private String role = "USER";

    /** Decision E: nothing is ever emailed to an address that has not confirmed itself. */
    @Column(name = "email_verified", nullable = false)
    private boolean emailVerified = false;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected UserEntity() {}

    UserEntity(String email, String passwordHash) {
        this.email = email;
        this.passwordHash = passwordHash;
    }

    Long getId() {
        return id;
    }

    String getEmail() {
        return email;
    }

    String getPasswordHash() {
        return passwordHash;
    }

    String getRole() {
        return role;
    }

    boolean isEmailVerified() {
        return emailVerified;
    }

    void markEmailVerified() {
        this.emailVerified = true;
    }
}

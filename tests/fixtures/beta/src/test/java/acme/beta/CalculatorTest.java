package acme.beta;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CalculatorTest {
    @Test
    void adds() {
        assertEquals(3.0, new Calculator().apply("+", 1, 2));
    }
}

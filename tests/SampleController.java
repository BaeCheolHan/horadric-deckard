package com.example.demo;

import org.springframework.web.bind.annotation.*;

/**
 * User Controller for managing user profiles.
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    /**
     * Get user by ID.
     * @param id User ID
     * @return User object
     */
    @GetMapping("/{id}")
    public String getUser(@PathVariable String id) {
        return "User: " + id;
    }

    @PostMapping("/create")
    public String createUser(@RequestBody String data) {
        return "Created: " + data;
    }
}

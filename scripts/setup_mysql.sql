-- Run as MySQL root, then copy .env.example to .env
CREATE DATABASE IF NOT EXISTS wallacesign CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'wallacesign'@'localhost' IDENTIFIED BY 'wallacesign';
CREATE USER IF NOT EXISTS 'wallacesign'@'127.0.0.1' IDENTIFIED BY 'wallacesign';
GRANT ALL PRIVILEGES ON wallacesign.* TO 'wallacesign'@'localhost';
GRANT ALL PRIVILEGES ON wallacesign.* TO 'wallacesign'@'127.0.0.1';
FLUSH PRIVILEGES;

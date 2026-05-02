# System-Resource-Monitoring-Alert-Script
System Monitor  is a powerful Python-based desktop application that provides real-time monitoring of system resources like CPU, RAM, Disk, and Network usage. It features live graphs, alert thresholds, email notifications, sound alerts, and performance logging in a modern GUI interface built with Tkinter.

 focusing on building practical cybersecurity and system tools.

##  Features
Real-Time Monitoring
CPU usage (including per-core visualization)
RAM (memory) usage
Disk usage
Network speed (upload/download)
CPU temperature (if supported)

## Live Graphs

Dynamic graph for CPU, RAM, and Disk usage
Historical data tracking (last 90 samples)

## Alert System

Custom thresholds for CPU, RAM, and Disk
Sound alerts 
OS notifications 
Email alerts  (with cooldown system)

## Email Notification System

SMTP-based alerts (Gmail supported)
Configurable sender & recipient
Test email feature
Secure password handling (base64 encoding)

## Logging System

Automatic logging every 10 seconds
CSV file storage (sysmon_log.csv)
Export logs anytime
Clear and refresh logs from UI

## Requirements

Install required dependency:

pip install psutil

## How to Run
python system_monitor_pro.py
Configuration
Email Alerts Setup
Use Gmail SMTP:
Host: smtp.gmail.com
Port: 587
Enable 2-Step Verification
Generate App Password
Enter credentials in app

##Key Concepts Used

Multithreading (background monitoring)
Tkinter GUI design
System monitoring with psutil
SMTP email automation
File handling (CSV logs)
Real-time data visualization



##Author

Taimoor Haider
Cybersecurity Engineering Student

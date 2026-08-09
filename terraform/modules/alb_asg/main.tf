resource "aws_lb" "main" {
  count = var.enabled ? 1 : 0

  name               = "${var.project}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_alb_id]
  subnets            = var.public_subnet_ids

  tags = {
    Name        = "${var.project}-alb"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_lb_target_group" "main" {
  count = var.enabled ? 1 : 0

  name     = "${var.project}-tg"
  port     = var.api_port
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }

  tags = {
    Name        = "${var.project}-tg"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_lb_listener" "main" {
  count = var.enabled ? 1 : 0

  load_balancer_arn = aws_lb.main[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.main[0].arn
  }
}

resource "aws_launch_template" "main" {
  count = var.enabled ? 1 : 0

  name_prefix   = "${var.project}-api-"
  image_id      = "ami-0abcdef1234567890"
  instance_type = "t3.micro"

  user_data = base64encode(<<-EOT
    #!/bin/bash
    docker run -d -p ${var.api_port}:${var.api_port} \
      --name taobao-api \
      taobao-api:latest
  EOT
  )

  network_interfaces {
    security_groups = [var.sg_api_ec2_id]
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${var.project}-api"
      Project     = var.project
      Environment = "localstack"
    }
  }
}

resource "aws_autoscaling_group" "main" {
  count = var.enabled ? 1 : 0

  name               = "${var.project}-asg"
  vpc_zone_identifier = var.private_subnet_ids
  min_size           = var.min_size
  max_size           = var.max_size
  desired_capacity   = var.min_size
  target_group_arns  = [aws_lb_target_group.main[0].arn]

  launch_template {
    id      = aws_launch_template.main[0].id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.project}-api"
    propagate_at_launch = true
  }
}
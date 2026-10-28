#pragma once
/* Minimal Unity replacement: count failed checks instead of aborting. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
extern int cnn_fail;
#define TEST_ASSERT_EQUAL(a, b) do { if ((a) != (b)) cnn_fail++; } while (0)
#define TEST_ASSERT_TRUE(x) do { if (!(x)) cnn_fail++; } while (0)

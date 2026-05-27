"""
Implementation of various ablation studies.
1. Removing RFC text, make the LLM rely solely on its learned knowledge to generate formats/parsers.
2. Removing Adversarial Refinement, to see how much it contributes to the overall performance.
3. Use different LLM models.
4. Removing optimizations to see how they reduce path counts

For 1 we implement a secondary driver that does not load RFC text and use adjusted prompts. We may use adversarial refinement but I suspect the performance will be poor.

For 2, since adversarial refinement is implemented in the driver, we can record the products before and after adversarial refinement to see the difference. So no code change is needed.

For 3, we can add a configuration option to the driver to select different LLM models. We can then run the same experiments with different models.

For 4, measuring path counts is already implemented in the driver. We can disable optimizations via configuration options and compare the path counts. But we do not need to actually run the experiments without optimizations, as the path counts are sufficient and running without optimizations may be too slow and burn through our LLM quota.

So in conclusion, we only need to implement 1 in code. The rest can be done via configuration and recording intermediate results.
"""

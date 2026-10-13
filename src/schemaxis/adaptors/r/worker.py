"""Trusted fixed R worker; authored identifiers never become formula symbols."""
WORKER=r'''args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==4L)
stage <- args[[1L]]
p <- as.integer(args[[2L]])
include_intercept <- as.integer(args[[3L]])==1L
has_heldout <- as.integer(args[[4L]])==1L
stopifnot(stage %in% c("fit","reopen"), p>=1L, p<=8L)
options(digits=17, scipen=999)
training <- utils::read.csv("training-input.csv", check.names=FALSE, stringsAsFactors=FALSE)
stopifnot(identical(names(training), c(paste0("x",seq_len(p)),"y")), all(vapply(training,is.numeric,logical(1L))), all(is.finite(as.matrix(training))))
if (stage=="fit") {
    formula <- stats::reformulate(paste0("x",seq_len(p)), response="y", intercept=include_intercept, env=baseenv())
    model <- stats::lm(formula, data=training, singular.ok=FALSE, na.action=stats::na.fail, model=TRUE, x=TRUE, y=TRUE)
    base::saveRDS(model, "model.rds", compress=FALSE, version=3L)
} else {
    model <- base::readRDS("model.rds")
    stopifnot(identical(class(model),"lm"))
}
stopifnot(model$rank==p+as.integer(include_intercept), model$df.residual==nrow(training)-model$rank)
write_table <- function(value, suffix) {
    utils::write.table(value, paste0(stage,"-",suffix,".csv"), sep=",", row.names=FALSE, col.names=TRUE, quote=FALSE, na="NA")
}
coefficient <- stats::coef(model)
stopifnot(all(is.finite(coefficient)))
write_table(data.frame(coefficientIndex=seq_along(coefficient)-1L,scaledCoefficient=unname(coefficient)),"coefficients")
write_table(data.frame(rank=model$rank,residualDF=model$df.residual),"metadata")
prediction <- unname(stats::predict(model,newdata=training))
stopifnot(all(is.finite(prediction)))
write_table(data.frame(sample=seq_len(nrow(training))-1L,observed=training$y,prediction=prediction,
    residual=training$y-prediction,fitted=unname(stats::fitted(model)),fitResidual=unname(stats::residuals(model))),"training")
if (has_heldout) {
    heldout <- utils::read.csv("heldout-input.csv",check.names=FALSE,stringsAsFactors=FALSE)
    stopifnot(identical(names(heldout),names(training)),all(vapply(heldout,is.numeric,logical(1L))),all(is.finite(as.matrix(heldout))))
    prediction <- unname(stats::predict(model,newdata=heldout))
    stopifnot(all(is.finite(prediction)))
    write_table(data.frame(sample=seq_len(nrow(heldout))-1L,observed=heldout$y,prediction=prediction,residual=heldout$y-prediction),"heldout")
}
writeLines(R.version.string,paste0(stage,"-runtime.txt"))
'''

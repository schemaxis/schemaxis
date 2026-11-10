# Copyright (C) 2026 David L F Gaden
"""Trusted fixed R worker; authored identifiers never become formula symbols."""
WORKER=r'''args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) %in% c(5L,6L))
stage <- args[[1L]]
p <- as.integer(args[[2L]])
include_intercept <- as.integer(args[[3L]])==1L
has_heldout <- as.integer(args[[4L]])==1L
has_inference <- !identical(args[[5L]],"none")
has_prediction <- length(args)==6L
stopifnot(stage %in% c("fit","reopen"), p>=1L, p<=8L)
if (has_prediction) {
    prediction_level <- as.numeric(args[[6L]])
    stopifnot(is.finite(prediction_level), prediction_level>=0.5, prediction_level<=0.999)
}
if (has_inference) {
    level <- as.numeric(args[[5L]])
    stopifnot(is.finite(level), level>=0.5, level<=0.999)
}
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
# Full round-trip precision; write.table keeps 15 digits and scipen expands tiny p-values.
write_exact <- function(value, suffix) {
    cells <- as.matrix(value)
    stopifnot(is.numeric(cells), all(is.finite(cells)))
    writeLines(c(paste(colnames(cells),collapse=","),apply(cells,1L,function(row) paste(sprintf("%.17g",row),collapse=","))),paste0(stage,"-",suffix,".csv"))
}
if (has_inference) {
    statistics <- stats::summary.lm(model)
    estimates <- stats::coef(statistics)
    stopifnot(identical(dim(estimates),c(model$rank,4L)), statistics$df[[1L]]==model$rank, statistics$df[[2L]]==model$df.residual, !is.null(statistics$fstatistic))
    interval <- stats::confint(model, level=level)
    stopifnot(identical(dim(interval),c(model$rank,2L)))
    f <- unname(statistics$fstatistic)
    write_exact(data.frame(coefficientIndex=seq_len(model$rank)-1L,scaledEstimate=unname(estimates[,1L]),scaledStandardError=unname(estimates[,2L]),
        tStatistic=unname(estimates[,3L]),pValue=unname(estimates[,4L]),scaledLower=unname(interval[,1L]),scaledUpper=unname(interval[,2L])),"inference")
    write_exact(data.frame(level=level,residualDF=model$df.residual,criticalValue=stats::qt(1-(1-level)/2,model$df.residual),sigma=statistics$sigma,
        rSquared=statistics$r.squared,adjustedRSquared=statistics$adj.r.squared,fStatistic=f[[1L]],fNumeratorDF=f[[2L]],fDenominatorDF=f[[3L]],
        fPValue=stats::pf(f[[1L]],f[[2L]],f[[3L]],lower.tail=FALSE)),"statistics")
}
if (has_prediction) {
    # Public stats::predict.lm on the genuine fitted/reopened lm: new rows hold predictors only.
    newdata <- utils::read.csv("prediction-input.csv",check.names=FALSE,stringsAsFactors=FALSE)
    stopifnot(identical(names(newdata),paste0("x",seq_len(p))),all(vapply(newdata,is.numeric,logical(1L))),all(is.finite(as.matrix(newdata))))
    confidence <- stats::predict.lm(model,newdata=newdata,se.fit=TRUE,interval="confidence",level=prediction_level)
    individual <- stats::predict.lm(model,newdata=newdata,se.fit=TRUE,interval="prediction",level=prediction_level)
    stopifnot(identical(dim(confidence$fit),c(nrow(newdata),3L)),identical(dim(individual$fit),c(nrow(newdata),3L)),
        confidence$df==model$df.residual,individual$df==model$df.residual,identical(unname(confidence$fit[,1L]),unname(individual$fit[,1L])))
    write_exact(data.frame(sample=seq_len(nrow(newdata))-1L,fit=unname(confidence$fit[,1L]),seFit=unname(confidence$se.fit),
        confidenceLower=unname(confidence$fit[,2L]),confidenceUpper=unname(confidence$fit[,3L]),
        individualLower=unname(individual$fit[,2L]),individualUpper=unname(individual$fit[,3L])),"prediction")
    write_exact(data.frame(level=prediction_level,residualDF=model$df.residual,criticalValue=stats::qt(1-(1-prediction_level)/2,model$df.residual),
        sigma=confidence$residual.scale,individualSigma=individual$residual.scale,confidenceDF=confidence$df,individualDF=individual$df),"prediction-statistics")
}
writeLines(R.version.string,paste0(stage,"-runtime.txt"))
'''

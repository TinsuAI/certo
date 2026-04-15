Function myVlookup(lookupValue, lookupRange, columnIndex As Long)
    Dim r As Range  'tao bien r chay
    Dim result As String
    result = ""
    For Each r In lookupRange
        If r = lookupValue Then
                result = result & ";" & r.Offset(0, columnIndex - 1)
        End If
    Next
    myVlookup = Right(result, Len(result) - 1)

End Function
